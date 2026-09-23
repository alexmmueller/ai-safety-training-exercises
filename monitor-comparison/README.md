# Monitor Comparison: Deterministic Rules vs Fine-tuned Classifier vs Prompted LLM Judge

A small, measured comparison of three approaches to catching off-task/suspicious
agent behavior, run against a shared 12-trajectory synthetic test set
(`trajectories.py`). This is the empirical follow-up to the
`inspect-deterministic-approver` prototype
(https://github.com/alexmmueller/inspect-deterministic-approver) -- it measures
where that approver's coverage actually stops, rather than asserting it.

## Setup

- **Deterministic approver**: `inspect-deterministic-approver`'s real
  `deterministic_rule_approver()`, run through actual Inspect AI approval
  objects (`ToolCall`, `ChatMessageAssistant`, history) for the fragmentation
  case, not a text approximation.
- **Fine-tuned classifier**: the LoRA DistilBERT adapter from the earlier
  training exercise (93.75% held-out accuracy on its own training
  distribution; **note**: this is the v1 classifier from 160 training
  examples. A later iteration series (v2-v4, see
  `../ontask-classifier/V4_RESULTS.md`) found this v1 model's accuracy
  looked strong here but did not generalize to novel semantic drift
  (45.8% at first, reaching 98.0% only after scaling to ~2,000 training
  examples) -- this comparison predates that finding and should be read
  alongside it, not in isolation).
- **Prompted LLM judge**: `qwen2.5:14b-instruct`, run fully locally via Ollama,
  zero-shot, asked to classify each (task, action) pair as on-task/off-task.

12 trajectories: 5 on-task, 7 off-task. The off-task set spans three
difficulty tiers: (a) 4 "obvious" attack-shaped actions (credential reads,
exfiltration, network scans -- modeled on the real OpenAI/Hugging Face
incident's failure pattern), (b) 2 "subtle drift" actions with no
attack-shaped keywords at all (an off-topic web search, an unrelated file
write), and (c) 1 fragmented command-injection case (modeled directly on
`inspect_ai#5133` -- the final tool-call fragment alone is meaningless; only
reassembling it against conversation history reveals the attack).

## Results

| Monitor | Overall accuracy | Off-task catch rate | Judge calls made |
|---|---|---|---|
| Deterministic approver | 83.3% | 71.4% (5/7) | 0 |
| Fine-tuned classifier | 83.3% | 71.4% (5/7) | 0 |
| Prompted LLM judge (standalone) | 100% | 100% (7/7) | 12/12 (every trajectory) |
| **Hybrid (deterministic → escalate to judge)** | **100%** | **100% (7/7)** | **7/12 (42% fewer)** |

Both the deterministic approver and the classifier caught all 4 "obvious"
attacks *and* the fragmented command-injection case (once tested through the
approver's real history-reassembly logic, not a naive single-string check).
Both missed the 2 "subtle drift" cases. The standalone LLM judge caught
everything, at the cost of a live model call on every single trajectory.

**The hybrid approver — deterministic rules first, escalating to the LLM
judge only when no rule matches — matches the standalone judge's full
100% catch rate while cutting judge calls by 42%.** This is the actual,
measured version of the harness thesis: composing a free deterministic
floor with a judgment layer reserved for what it can't cover, rather than
asserting the idea in prose. Built as real, runnable code
(`inspect_deterministic_approver.hybrid.hybrid_approver`) using Inspect
AI's native `ApprovalPolicy` escalation mechanism (the `"escalate"`
decision, which Inspect AI already supports for exactly this
compose-multiple-approvers pattern), not a bespoke wrapper — and verified
end-to-end through Inspect AI's real `apply_tool_approval` machinery
(`tests/hybrid_integration_test.py`), not mocks.

## What this actually shows

**Rules and a cheap classifier give you free, zero-latency, zero-ambiguity
coverage on the mechanically-detectable subset of attacks** -- including the
fragmentation-bypass class that a naive single-call check would miss entirely
(this is the direct empirical validation of what the deterministic approver
was built to fix). Neither can catch semantic drift with no attack-shaped
signature by construction: a regex has nothing to match on `web_search('best
pizza restaurants')`, and a small classifier trained on attack-pattern
examples generalizes to attack patterns, not to arbitrary off-topic behavior.

**The LLM judge catches everything tested here, but at real, non-zero cost**:
every decision is a live model call (~0.4s each locally; real latency and $
cost against a frontier API at production scale), and unlike the deterministic
approver, its decisions are not fully auditable or provably consistent --
a differently-phrased prompt or a slightly different model could plausibly
produce a different answer on the same input.

**This is the actual argument for composing layers, not choosing one:** put
the deterministic approver in front, for free, to catch the cheap/obvious
cases (including fragmentation, which nothing else here caught without the
specific history-reassembly fix) -- and reserve the expensive judgment layer
for what's left, rather than running it on every single tool call. That's a
direct, load-bearing claim about system design, not just "add more layers" --
and it's now backed by a number (5/7 caught for free) instead of an assertion.

## Honest limitations of this comparison

- **N=12 is tiny.** This is a first measured pass, not a benchmark. The
  catch-rate numbers would move with a larger, more varied test set --
  treat the *qualitative* finding (rules/classifier catch obvious+
  fragmented attacks for free, both miss semantic drift, judge catches
  drift at a cost) as the real result, not the exact percentages.
- **All examples are synthetic and hand-constructed by me**, including the
  "subtle drift" cases specifically designed to be hard for rules/classifiers.
  This measures a known, deliberately-constructed gap, not a discovered one --
  a genuinely novel real-world drift pattern might behave differently.
- **The judge's 100% here is a best-case result on an easy test set** for a
  capable local model with zero adversarial pressure on the judge itself.
  It says nothing about the judge's own robustness to manipulation (e.g. an
  agent crafting an action description to read as benign to the judge) --
  that's a different, harder question this comparison doesn't test.
- **No cost/latency measurement at scale** -- the "cheap vs expensive" claim
  is qualitatively obvious (a regex match vs a model call) but not
  quantified here beyond the raw per-call latency shown.

## Reproduce

```
cd monitor-comparison
python compare_monitors.py
```

Requires the LoRA classifier adapter (`/tmp/ontask_classifier_lora_final`,
from `finetune_ontask_classifier.py`), `inspect-deterministic-approver`
installed, and Ollama running `qwen2.5:14b-instruct` locally.

Full raw results: `comparison_results.json`. Run log: `run_output.log`.
