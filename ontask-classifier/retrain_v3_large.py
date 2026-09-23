"""
v3 retraining: much larger dataset (630 training examples, up from 240 in
v2), testing whether MORE DATA closes the generalization gap diagnosed in
DIAGNOSTIC_RESULTS.md (v2 showed near-random, bimodal behavior on novel
phrasing -- 45.8% held-out catch rate, not explained by a single fixable
shortcut).

Held-out set (360 examples) uses drift SUBJECTS never seen in training at
all (not just new phrasings of the same subjects) -- the honest test.

Run: python retrain_v3_large.py
"""

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

from large_dataset_v3 import build_v3_held_out_set, build_v3_training_set

torch.manual_seed(42)

MODEL_NAME = "distilbert-base-uncased"
SAVE_DIR = "/tmp/ontask_classifier_lora_v3_large"

# ---------------------------------------------------------------------------
# 1. Dataset
# ---------------------------------------------------------------------------

examples = build_v3_training_set()
print(f"Built {len(examples)} training examples "
      f"({sum(e['label'] for e in examples)} on-task, "
      f"{sum(1 - e['label'] for e in examples)} off-task)")

split = int(len(examples) * 0.85)
train_examples = examples[:split]
eval_examples = examples[split:]
print(f"Train: {len(train_examples)}  |  Eval (same distribution): {len(eval_examples)}")

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
    output_dir="/tmp/ontask_classifier_v3_run",
    num_train_epochs=6,
    per_device_train_batch_size=16,
    per_device_eval_batch_size=16,
    learning_rate=2e-4,
    eval_strategy="epoch",
    save_strategy="no",
    logging_steps=20,
    report_to=[],
)

trainer = Trainer(
    model=model, args=training_args,
    train_dataset=train_ds, eval_dataset=eval_ds,
    compute_metrics=compute_metrics,
)

trainer.train()

metrics = trainer.evaluate()
print("\n=== SAME-DISTRIBUTION EVAL ===")
print(metrics)

model.save_pretrained(SAVE_DIR)
tokenizer.save_pretrained(SAVE_DIR)
print(f"\nSaved to {SAVE_DIR}")

# ---------------------------------------------------------------------------
# 3. THE REAL TEST: held-out drift subjects never seen in training at all
# ---------------------------------------------------------------------------

model.eval()
model.to(device)

held_out = build_v3_held_out_set()
print(f"\n=== GENERALIZATION TEST: {len(held_out)} held-out drift examples "
      f"(subjects never seen in training) ===")

correct = 0
by_subject: dict[str, list[bool]] = {}
for ex in held_out:
    inputs = tokenizer(ex["text"], return_tensors="pt", truncation=True, max_length=64)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        logits = model(**inputs).logits
    pred = int(torch.argmax(logits, dim=-1).item())
    is_correct = pred == ex["label"]
    correct += int(is_correct)
    # crude subject extraction from the action string for grouping
    by_subject.setdefault(ex["action"], []).append(is_correct)

held_out_accuracy = correct / len(held_out)
print(f"\nHeld-out drift catch rate: {correct}/{len(held_out)} ({held_out_accuracy:.1%})")
print(f"(v2 comparison: 45.8% on 72 examples with 240 training examples)")
print(f"(v3: {held_out_accuracy:.1%} on {len(held_out)} examples with {len(train_examples)} training examples)")

print("\nPer-action-string catch rate (sample):")
for action, results in sorted(by_subject.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))[:15]:
    rate = sum(results) / len(results)
    print(f"  {rate:5.0%}  {action[:70]}")
