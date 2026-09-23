"""
v4 (FINAL iteration): ~2,000 training examples, the largest and last
dataset scale-up in this series. See V4_RESULTS.md for the final numbers
and the complete iteration history (v1 -> v2 -> v3 -> v4).

Run: python retrain_v4_final.py
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

from large_dataset_v4 import build_v4_held_out_set, build_v4_training_set

torch.manual_seed(42)

MODEL_NAME = "distilbert-base-uncased"
SAVE_DIR = "/tmp/ontask_classifier_lora_v4_final"

examples = build_v4_training_set()
print(f"Built {len(examples)} training examples "
      f"({sum(e['label'] for e in examples)} on-task, "
      f"{sum(1 - e['label'] for e in examples)} off-task)")

split = int(len(examples) * 0.9)
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
    output_dir="/tmp/ontask_classifier_v4_run",
    num_train_epochs=5,
    per_device_train_batch_size=32,
    per_device_eval_batch_size=32,
    learning_rate=2e-4,
    eval_strategy="epoch",
    save_strategy="no",
    logging_steps=30,
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

model.eval()
model.to(device)

held_out = build_v4_held_out_set()
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
    by_subject.setdefault(ex["action"], []).append(is_correct)

held_out_accuracy = correct / len(held_out)
print(f"\nHeld-out drift catch rate: {correct}/{len(held_out)} ({held_out_accuracy:.1%})")
print("\nIteration history:")
print("  v2: 45.8% (72 held-out examples, 240 training examples)")
print("  v3: 95.6% (360 held-out examples, 630 training examples)")
print(f"  v4: {held_out_accuracy:.1%} ({len(held_out)} held-out examples, {len(train_examples)} training examples)")

print("\nWorst-performing held-out actions (if any below 100%):")
failing = [(a, sum(r) / len(r)) for a, r in by_subject.items() if sum(r) / len(r) < 1.0]
if failing:
    for action, rate in sorted(failing, key=lambda x: x[1]):
        print(f"  {rate:5.0%}  {action[:70]}")
else:
    print("  (none -- 100% on every distinct held-out action string)")
