# AI Safety Training Exercises

Hands-on exercises building real, verifiable contact with model training
and eval infrastructure -- not toy demos disconnected from the
observability-harness thesis, but direct precursors to it.

**Quick orientation -- the classifier iteration arc (sections 2, 4-7):**

| Version | Training examples | Held-out drift catch rate | Doc |
|---|---|---|---|
| v1 | 160 | not measured on drift specifically | section 2 below |
| v2 | 240 | 45.8% (72 held-out) | `ontask-classifier/RETRAIN_RESULTS.md` |
| v2 diagnostic | (same model as v2) | 46.3% (216 held-out, broader test) | `ontask-classifier/DIAGNOSTIC_RESULTS.md` |
| v3 | 630 | 95.6% (360 held-out) | `ontask-classifier/V3_RESULTS.md` |
| v4 (final) | 1,980 | **98.0%** (1,080 held-out) | `ontask-classifier/V4_RESULTS.md` |

Read `V4_RESULTS.md` first if you only read one -- it has the full
iteration table and the final, corrected conclusion. The other docs are
kept as-is (with inline corrections noted) to show how the investigation
actually progressed, including a wrong turn along the way.

## 1. `boolq-eval/` -- running real eval infrastructure end-to-end

Ran `inspect_evals`' `boolq` benchmark against a fully local model
(`qwen2.5:3b` via Ollama, no API keys/cost) using Inspect AI's actual eval
pipeline -- the same framework behind the tool-call approval bugs
(inspect_ai#5133, #5132) already reproduced and reported.

**Result:** 90% accuracy (10 samples, stderr 0.10). Full structured eval
log (model prompts, responses, per-sample scoring) in `logs/`.

**Why this matters for the thesis:** understanding Inspect AI's Task /
Solver / Scorer / eval-log model from the inside is a precondition for
building the custom Scorer-based LLM-judge monitor (next planned step) and
for correctly reasoning about where the approver extension point sits in
the pipeline.

## 2. `ontask-classifier/` -- LoRA fine-tune of an on-task/off-task classifier (v1, superseded -- see below)

A small, end-to-end supervised fine-tune: LoRA adapter on
`distilbert-base-uncased`, classifying `(task instruction, agent action)`
pairs as on-task (1) or off-task/suspicious (0).

**This is the FIRST of four iterations (v1-v4) on this classifier.** The
full arc -- train, find it doesn't generalize, diagnose why, scale data,
and measure the fix -- is section 7 below. This section describes v1 as
originally built; sections 4-7 describe what came next.

**Dataset:** 160 synthetic examples -- 10 realistic agent tasks (crawl a
site, fix a test, summarize a doc, etc.), each paired with genuine on-task
actions and with off-task actions modeled directly on the OpenAI/Hugging
Face incident's actual failure pattern (credential exfiltration, unrelated
third-party network access, hidden-channel coordination messages).

**Training:** LoRA (r=8, alpha=16) on DistilBERT's attention projections --
739,586 trainable params out of 67.7M total (1.09%). Ran on Apple M5 GPU
via PyTorch MPS backend. 6 epochs, ~4.5s total training time.

**Results:**
- Held-out eval accuracy: 93.75%, F1: 0.957
- Sanity check on 4 genuinely novel (task, action) pairs not in train or
  eval sets: 4/4 correct

**Honest limitations, as understood at the time (largely resolved by v4 --
see section 7):**
- Fully synthetic data, hand-constructed by me -- not real agent
  trajectories.
- Toy scale (160 examples, single-line actions) -- this is a mechanics
  exercise, not the actual harness classifier.
- No comparison yet against a prompted LLM-judge baseline on the same
  examples (done in section 3 below).

**Why this matters for the thesis:** this is the direct, minimal precursor
to the "behavioral anomaly classifier" component of the planned open-source
observability harness -- same problem shape (label an action against a
stated task), same intended use (flagging deviations like the HF-incident
coordination pattern), scaled down to something buildable in an afternoon.

## Environment

- `boolq-eval`: `/tmp/inspect_venv` (Python 3.11, inspect_ai editable
  install + inspect_evals + openai client for Ollama's OpenAI-compatible
  API)
- `ontask-classifier`: `/tmp/finetune_venv` (Python 3.11, torch + transformers
  + peft + accelerate + datasets + scikit-learn)

Both venvs are in `/tmp` (ephemeral) -- rerun `pip install` from the
package lists above to reproduce.

## 3. Monitor comparison: deterministic rules vs classifier vs prompted LLM judge

See `monitor-comparison/README.md` for the full writeup. Headline result:
deterministic approver and fine-tuned classifier both catch 5/7 off-task
trajectories for free (including the #5133 fragmentation case, via real
history reassembly) -- both miss 2 "subtle drift" cases with no attack
signature. A prompted LLM judge (qwen2.5:14b-instruct, local) catches
7/7, at the cost of a live model call per decision.

**This is the empirical backbone for the harness thesis**: compose a free
deterministic layer for cheap/obvious+fragmented attacks with a judgment
layer reserved for semantic drift, rather than running an expensive judge
on every tool call.

## 4. Retraining v2: targeting the semantic-drift gap, with a real generalization test

See `ontask-classifier/RETRAIN_RESULTS.md` for the full writeup. Retrained
the classifier on an expanded dataset including drift negatives, then
measured it on a **held-out drift set never seen in training** (the honest
test of generalization, not memorization).

**Result: 33/72 (45.8%) held-out drift catch rate** -- real improvement
over the original classifier's 0% on drift. At the time, this was read as
evidence the classifier had a specific, fixable shortcut. That read was
tested directly next (section 5) and the picture got more nuanced --
see sections 5-7 for how the conclusion evolved.

## 5. Diagnostic test + expanded generalization test -- theory revised

See `ontask-classifier/DIAGNOSTIC_RESULTS.md`. Tested the v2 "tool-name
shortcut" hypothesis directly (same content, different tool wrappers) and
with a larger 216-example held-out set -- the data **overturned the simple
version of the theory**: the classifier showed near-random, bimodal
behavior on novel phrasing rather than one clean, fixable shortcut. At
this point the working conclusion was that a small synthetic-data
fine-tune "doesn't reliably generalize at all" -- **this conclusion was
itself too strong and was corrected in sections 6-7 below.**

## 6. v3: scaling training data substantially closes the generalization gap

See `ontask-classifier/V3_RESULTS.md`. Scaled training data 2.6x (630 vs
240 examples). **Result: 95.6% (344/360) held-out catch rate**, up from
45.8% -- directly disproving the "doesn't reliably generalize at all"
claim from section 5. Revised conclusion: a small classifier *can*
generalize well, given enough varied training data.

## 7. v4 (FINAL): ~2,000 training examples -- the converged result

See `ontask-classifier/V4_RESULTS.md` for the full iteration table and
final numbers. Scaled to 1,980 training examples (up from 630).

**Result: 1058/1080 (98.0%) held-out drift catch rate** -- the highest and
final number in this series, with diminishing but real returns at each
scale-up (45.8% -> 95.6% -> 98.0%). Two residual, explainable failures
remain (subjects that plausibly read as work-adjacent, not random noise).

**Final conclusion**, superseding every earlier one in this arc: a small,
cheap LoRA fine-tune on DistilBERT can reach ~98% generalization to novel
semantic drift, but needs roughly 8x more training data than an
afternoon-scale exercise provides to get there. The LLM judge's practical
advantage isn't raw ceiling accuracy (the classifier ultimately matches
it) -- it's needing zero training-data construction effort and having no
equivalent blind spot for genuinely ambiguous, work-adjacent-sounding
topics, which is the harder problem synthetic data scaling doesn't
fully solve.

## 8. Open-weight CoT monitor (pilot, honest limitations)

See `cot-monitor/README.md`. Built a chain-of-thought monitor against
OPEN-WEIGHT reasoning models (DeepSeek-R1 via Ollama), motivated by the
fact that hosted APIs (Anthropic, OpenAI) deliberately withhold raw CoT --
both expose only a provider-generated summary. Confirmed empirically that
Ollama exposes genuine, unfiltered raw CoT with no summarization step.

Ran a first pilot experiment measuring whether monitor-relevant reasoning
signal survives summarization (using a second local model as a stand-in
summarizer). **Honest result: only 1 flag fired across 4 designed
scenarios (using a small 1.5B reasoning model), and it did not survive
summarization -- but the sample is too small to report a reliable
"survival rate," and reading the raw traces shows the small model mostly
didn't engage with the scenarios' embedded ethical/scope tension at all.**
Reported as: a working, reproducible pipeline + one illustrative case, not
a completed measurement. Honest next step (larger reasoning model,
redesigned scenarios) documented, not yet done.
