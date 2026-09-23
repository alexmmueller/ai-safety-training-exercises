"""
Retrain the on-task/off-task classifier on an expanded dataset that
includes genuine semantic-drift negatives (no attack-shaped keywords),
and -- the important part -- measure it on a HELD-OUT drift set that was
never seen in training, to test generalization rather than memorization.

This directly targets the gap found in the original 4-way monitor
comparison: both the deterministic approver (by design -- it has no rule
for keyword-less drift) and the FIRST classifier (trained only on
attack-shaped negatives) missed 2/2 semantic-drift cases in that test.

Run: python retrain_with_drift.py
"""

import random

import numpy as np
import torch
from datasets import Dataset
from peft import LoraConfig, TaskType, get_peft_model
from sklearn.metrics import accuracy_score, f1_score
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)

from expanded_dataset import build_expanded_training_examples, build_held_out_drift_examples

random.seed(42)
torch.manual_seed(42)

MODEL_NAME = "distilbert-base-uncased"
SAVE_DIR = "/tmp/ontask_classifier_lora_v2_drift"

# ---------------------------------------------------------------------------
# 1. Dataset
# ---------------------------------------------------------------------------

examples = build_expanded_training_examples()
print(f"Built {len(examples)} training examples "
      f"({sum(e['label'] for e in examples)} on-task, "
      f"{sum(1 - e['label'] for e in examples)} off-task "
      f"[attack + train-drift negatives])")

split = int(len(examples) * 0.85)
train_examples = examples[:split]
eval_examples = examples[split:]

train_ds = Dataset.from_list(train_examples)
eval_ds = Dataset.from_list(eval_examples)

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)


def tokenize(batch):
    return tokenizer(batch["text"], truncation=True, padding="max_length", max_length=64)


train_ds = train_ds.map(tokenize, batched=True).remove_columns(["text"])
eval_ds = eval_ds.map(tokenize, batched=True).remove_columns(["text"])
train_ds.set_format("torch")
eval_ds.set_format("torch")

# ---------------------------------------------------------------------------
# 2. Model + LoRA
# ---------------------------------------------------------------------------

base_model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=2)
lora_config = LoraConfig(
    task_type=TaskType.SEQ_CLS, r=8, lora_alpha=16, lora_dropout=0.1,
    target_modules=["q_lin", "v_lin"],
)
model = get_peft_model(base_model, lora_config)
model.print_trainable_parameters()

device = "mps" if torch.backends.mps.is_available() else "cpu"
print(f"Training on device: {device}")


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    return {"accuracy": accuracy_score(labels, preds), "f1": f1_score(labels, preds)}


training_args = TrainingArguments(
    output_dir="/tmp/ontask_classifier_v2_run",
    num_train_epochs=8,
    per_device_train_batch_size=8,
    per_device_eval_batch_size=8,
    learning_rate=2e-4,
    eval_strategy="epoch",
    save_strategy="no",
    logging_steps=10,
    report_to=[],
)

trainer = Trainer(
    model=model, args=training_args,
    train_dataset=train_ds, eval_dataset=eval_ds,
    compute_metrics=compute_metrics,
)

trainer.train()

metrics = trainer.evaluate()
print("\n=== HELD-OUT EVAL (same distribution as training) ===")
print(metrics)

model.save_pretrained(SAVE_DIR)
tokenizer.save_pretrained(SAVE_DIR)
print(f"\nSaved to {SAVE_DIR}")

# ---------------------------------------------------------------------------
# 3. THE REAL TEST: genuinely unseen drift examples, never in training
# ---------------------------------------------------------------------------

model.eval()
model.to(device)

held_out = build_held_out_drift_examples()
print(f"\n=== GENERALIZATION TEST: {len(held_out)} HELD-OUT drift examples "
      f"(never seen in training) ===")

correct = 0
for ex in held_out:
    text = f"task: {ex['task']} action: {ex['action']}"
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=64)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        logits = model(**inputs).logits
    pred = int(torch.argmax(logits, dim=-1).item())
    is_correct = pred == ex["label"]
    correct += int(is_correct)
    mark = "✓" if is_correct else "✗"
    print(f"  [{mark}] pred={pred} true={ex['label']} | {ex['action'][:60]}")

held_out_accuracy = correct / len(held_out)
print(f"\nHeld-out drift catch rate: {correct}/{len(held_out)} ({held_out_accuracy:.1%})")
print("(This measures GENERALIZATION to drift patterns never seen in "
      "training -- the honest test of whether retraining actually helped, "
      "not just memorized the training set.)")
