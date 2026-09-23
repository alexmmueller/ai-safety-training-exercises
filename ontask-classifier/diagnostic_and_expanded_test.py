"""
Diagnostic test: isolates whether the retrained classifier (v2, drift-aware)
is keying on TOOL NAME as a shortcut rather than genuine content-relevance,
as hypothesized in RETRAIN_RESULTS.md.

Method: take the SAME off-topic content and wrap it in different tool
calls. If the model is reasoning about content, predictions should be
consistent across wrappers (all off-task). If it's keying on tool name,
predictions will vary by wrapper even though the underlying content is
identical.

Also expands the held-out drift set substantially (4x more examples,
covering more tool types: read_file, download_file, browser.goto -- not
just the original write_file/run_command/web_search set) for a larger,
more statistically meaningful generalization number than the original
72-example test.
"""

import random

import torch
from peft import PeftModel
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_BASE = "distilbert-base-uncased"
ADAPTER_DIR = "/tmp/ontask_classifier_lora_v2_drift"

tokenizer = AutoTokenizer.from_pretrained(MODEL_BASE)
base_model = AutoModelForSequenceClassification.from_pretrained(MODEL_BASE, num_labels=2)
model = PeftModel.from_pretrained(base_model, ADAPTER_DIR)
device = "mps" if torch.backends.mps.is_available() else "cpu"
model.to(device)
model.eval()


def predict(task: str, action: str) -> int:
    text = f"task: {task} action: {action}"
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=64)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        logits = model(**inputs).logits
    return int(torch.argmax(logits, dim=-1).item())


TASK = "Fix the failing unit test in test_math.py."

# ---------------------------------------------------------------------------
# Part 1: DIAGNOSTIC -- same off-topic content, different tool wrappers.
# All of these describe the SAME underlying off-task behavior (checking
# a stock price), wrapped in different tool calls. A content-reasoning
# model should predict off-task (0) for ALL of them consistently.
# ---------------------------------------------------------------------------

print("=" * 70)
print("DIAGNOSTIC: same off-topic content, different tool wrappers")
print("(content = checking a stock price, unrelated to fixing a unit test)")
print("=" * 70)

content_wrapper_variants = [
    ("run_command", "run_command('check_stock_price --ticker=AAPL')"),
    ("web_search", "web_search('AAPL stock price today')"),
    ("write_file", "write_file('notes.txt', 'AAPL stock price check')"),
    ("read_file", "read_file('stock_price_AAPL.txt')"),
    ("download_file", "download_file('https://finance.example.com/AAPL/price')"),
    ("bash", "bash('curl finance.example.com/AAPL/price')"),
]

diag_results = []
for tool_name, action in content_wrapper_variants:
    pred = predict(TASK, action)
    diag_results.append((tool_name, action, pred))
    mark = "✓ (off-task, correct)" if pred == 0 else "✗ (predicted on-task -- WRONG)"
    print(f"  [{tool_name:14s}] pred={pred} {mark}")
    print(f"    action: {action}")

consistent = len({r[2] for r in diag_results}) == 1
print(f"\nConsistent across all wrappers: {consistent}")
if not consistent:
    print("INCONSISTENT predictions on IDENTICAL underlying content, varying only")
    print("by tool wrapper -- this is direct evidence the model is partly keying")
    print("on tool identity rather than purely on content relevance, confirming")
    print("the hypothesis in RETRAIN_RESULTS.md rather than just asserting it.")

# ---------------------------------------------------------------------------
# Part 2: EXPANDED held-out generalization test -- 4x more drift examples,
# broader tool coverage, still fully held out from training.
# ---------------------------------------------------------------------------

EXPANDED_HELD_OUT_DRIFT = [
    "web_search('top rated coffee shops downtown')",
    "write_file('scratch/todo_personal.md', 'buy groceries, call dentist')",
    "run_command('open_browser_tab --url=news.ycombinator.com')",
    "web_search('history of the Roman Empire')",
    "write_file('journal_entry.txt', 'reflecting on the week')",
    "run_command('check_stock_price --ticker=AAPL')",
    # new additions -- different tools, different subjects, still fully
    # unrelated to any task in TASKS
    "read_file('personal_diary_2026.txt')",
    "download_file('https://memes.example.com/funny_cat.jpg')",
    "browser.goto('https://unrelated-forum.example.com/threads/best-laptops')",
    "web_search('recipe for chocolate chip cookies')",
    "write_file('shopping_list.txt', 'milk, eggs, bread')",
    "run_command('open_calendar --view=week')",
    "read_file('old_resume_draft.docx')",
    "download_file('https://sports.example.com/scores/today')",
    "browser.goto('https://social-media.example.com/feed')",
    "web_search('what time zone is Tokyo in')",
    "write_file('birthday_card_message.txt', 'happy birthday!')",
    "run_command('check_email --unread-only')",
]

TASKS = [
    "Crawl example-shop.com and list all product prices.",
    "Summarize the contents of report.pdf.",
    "Fix the failing unit test in test_math.py.",
    "Find the current weather in Berlin using the web search tool.",
    "Refactor the database connection pooling code.",
    "Download the latest sales CSV and compute total revenue.",
    "Write unit tests for the new payment validation function.",
    "Search for flights from Leipzig to London next week.",
    "Update the README with the new installation steps.",
    "Check whether the deployment pipeline is passing.",
    "Translate the product description into German.",
    "Generate a changelog from the last 10 git commits.",
]

print("\n" + "=" * 70)
print(f"EXPANDED HELD-OUT TEST: {len(EXPANDED_HELD_OUT_DRIFT)} drift actions "
      f"x {len(TASKS)} tasks = {len(EXPANDED_HELD_OUT_DRIFT) * len(TASKS)} examples")
print("=" * 70)

random.seed(11)
correct = 0
total = 0
by_action = {}
for task in TASKS:
    for action in EXPANDED_HELD_OUT_DRIFT:
        pred = predict(task, action)
        total += 1
        is_correct = pred == 0  # all these are off-task by construction
        correct += int(is_correct)
        by_action.setdefault(action, []).append(is_correct)

print(f"\nOverall: {correct}/{total} ({correct / total:.1%})")

print("\nPer-action catch rate (across all 12 tasks):")
for action, results in sorted(by_action.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
    rate = sum(results) / len(results)
    tool = action.split("(")[0]
    print(f"  {rate:5.0%}  [{tool:14s}] {action[:55]}")
