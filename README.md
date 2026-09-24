# AI Safety Training Exercises

Two hands-on exercises building real, verifiable contact with model
training, eval, and interpretability infrastructure -- not toy demos
disconnected from the observability-harness thesis, but direct
precursors to it. Both exercises attack the same underlying problem
(catching an agent that's doing something it shouldn't) from opposite
ends: **Exercise A** watches an agent's *behavior* from the outside
(black-box); **Exercise B** watches a model's *internal activations*
from the inside (white-box). Read either one first -- they don't depend
on each other.

---

## Exercise A: Black-box behavioral monitoring -- deterministic rules vs. a fine-tuned classifier vs. an LLM judge

**The question:** given an agent's stated task and the actions it
actually takes, can you catch it going off-task or behaving
suspiciously -- without reading its internal activations at all, just
its observable behavior?

**Quick orientation -- the classifier iteration arc (A2, A4-A7):**

| Version | Training examples | Held-out drift catch rate | Doc |
|---|---|---|---|
| v1 | 160 | not measured on drift specifically | section A2 below |
| v2 | 240 | 45.8% (72 held-out) | `ontask-classifier/RETRAIN_RESULTS.md` |
| v2 diagnostic | (same model as v2) | 46.3% (216 held-out, broader test) | `ontask-classifier/DIAGNOSTIC_RESULTS.md` |
| v3 | 630 | 95.6% (360 held-out) | `ontask-classifier/V3_RESULTS.md` |
| v4 (final) | 1,980 | **98.0%** (1,080 held-out) | `ontask-classifier/V4_RESULTS.md` |

Read `V4_RESULTS.md` first if you only read one -- it has the full
iteration table and the final, corrected conclusion. The other docs are
kept as-is (with inline corrections noted) to show how the investigation
actually progressed, including a wrong turn along the way.

### A1. `boolq-eval/` -- running real eval infrastructure end-to-end

Ran `inspect_evals`' `boolq` benchmark against a fully local model
(`qwen2.5:3b` via Ollama, no API keys/cost) using Inspect AI's actual eval
pipeline -- the same framework behind the tool-call approval bugs
(inspect_ai#5133, #5132) already reproduced and reported.

**Result:** 90% accuracy (10 samples, stderr 0.10). Full structured eval
log (model prompts, responses, per-sample scoring) in `logs/`.

**Why this matters for the thesis:** understanding Inspect AI's Task /
Solver / Scorer / eval-log model from the inside is a precondition for
building the custom Scorer-based LLM-judge monitor (used in A3) and for
correctly reasoning about where the approver extension point sits in
the pipeline.

### A2. `ontask-classifier/` -- LoRA fine-tune of an on-task/off-task classifier (v1, superseded -- see below)

A small, end-to-end supervised fine-tune: LoRA adapter on
`distilbert-base-uncased`, classifying `(task instruction, agent action)`
pairs as on-task (1) or off-task/suspicious (0).

**This is the FIRST of four iterations (v1-v4) on this classifier.** The
full arc -- train, find it doesn't generalize, diagnose why, scale data,
and measure the fix -- is section A7 below. This section describes v1 as
originally built; sections A4-A7 describe what came next.

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
see section A7):**
- Fully synthetic data, hand-constructed by me -- not real agent
  trajectories.
- Toy scale (160 examples, single-line actions) -- this is a mechanics
  exercise, not the actual harness classifier.
- No comparison yet against a prompted LLM-judge baseline on the same
  examples (done in A3 below).

**Why this matters for the thesis:** this is the direct, minimal precursor
to the "behavioral anomaly classifier" component of the planned open-source
observability harness -- same problem shape (label an action against a
stated task), same intended use (flagging deviations like the HF-incident
coordination pattern), scaled down to something buildable in an afternoon.

### A3. Monitor comparison: deterministic rules vs classifier vs prompted LLM judge

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

### A4. Retraining v2: targeting the semantic-drift gap, with a real generalization test

See `ontask-classifier/RETRAIN_RESULTS.md` for the full writeup. Retrained
the classifier on an expanded dataset including drift negatives, then
measured it on a **held-out drift set never seen in training** (the honest
test of generalization, not memorization).

**Result: 33/72 (45.8%) held-out drift catch rate** -- real improvement
over the original classifier's 0% on drift. At the time, this was read as
evidence the classifier had a specific, fixable shortcut. That read was
tested directly next (A5) and the picture got more nuanced -- see A5-A7
for how the conclusion evolved.

### A5. Diagnostic test + expanded generalization test -- theory revised

See `ontask-classifier/DIAGNOSTIC_RESULTS.md`. Tested the v2 "tool-name
shortcut" hypothesis directly (same content, different tool wrappers) and
with a larger 216-example held-out set -- the data **overturned the simple
version of the theory**: the classifier showed near-random, bimodal
behavior on novel phrasing rather than one clean, fixable shortcut. At
this point the working conclusion was that a small synthetic-data
fine-tune "doesn't reliably generalize at all" -- **this conclusion was
itself too strong and was corrected in A6-A7 below.**

### A6. v3: scaling training data substantially closes the generalization gap

See `ontask-classifier/V3_RESULTS.md`. Scaled training data 2.6x (630 vs
240 examples). **Result: 95.6% (344/360) held-out catch rate**, up from
45.8% -- directly disproving the "doesn't reliably generalize at all"
claim from A5. Revised conclusion: a small classifier *can* generalize
well, given enough varied training data.

### A7. v4 (FINAL): ~2,000 training examples -- the converged result

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

**Environment:** `boolq-eval` used `/tmp/inspect_venv` (Python 3.11,
inspect_ai editable install + inspect_evals + openai client for Ollama's
OpenAI-compatible API); `ontask-classifier` used `/tmp/finetune_venv`
(Python 3.11, torch + transformers + peft + accelerate + datasets +
scikit-learn). Both venvs were ephemeral (`/tmp`) -- rerun `pip install`
from the package lists above to reproduce.

---

## Exercise B: White-box activation probing -- reading a local model's internals live, in an agent loop

**The question:** instead of watching an agent's external behavior
(Exercise A), can you read a local open-weight model's *internal
activations* while it works, and detect a deception/misalignment signal
directly from its residual stream?

### B1. `hermes-plugins/local_activation_probe/` -- deception probing on a local model, wired into a real Hermes plugin

A general-purpose Hermes plugin that reads a **local open-weight model's
internal activations** during real agent use and scores them against a
linear probe for deception/misalignment signals -- implementing the
mainline methodology of Apollo Research's ["Detecting Strategic
Deception Using Linear Probes"](https://arxiv.org/abs/2502.03407)
(arXiv:2502.03407, read in full, not summarized secondhand -- see
`hermes-plugins/local_activation_probe/README.md` for exact quotes and
section references).

**Model-agnostic and probe-agnostic**: point it at any HuggingFace
model, train your own probe on your own labeled examples. Implements
the paper's actual primary method (logistic regression, L2
regularized), per-token normalization, and mean-over-all-tokens
aggregation -- not a simplified approximation of the paper, closed gap
by gap and logged honestly where an earlier draft got the methodology
wrong (see the plugin's own verification log for the correction trail).

**Getting a working local activation-extraction pipeline running on
Apple Silicon took real debugging**, documented start to finish:
vLLM's native `extract_hidden_states` is CUDA-only in practice (a
`NotImplementedError` from `vllm-metal`'s own source, confirmed
directly); NNsight segfaults on MPS but works cleanly on CPU (confirmed
reproducibly); MPS activations themselves were checked and found
numerically trustworthy before ruling MPS out for the segfault reason
specifically, not assumed either way.

**New experiment beyond the paper**: an out-of-distribution
generalization test across five domains the probe never trained on
(logistics, healthcare, aviation, weather, corporate finance). Real
result: the simpler difference-of-means baseline nearly failed on a
held-out finance example (score -1.494, close to crossing into "honest"
territory) while logistic regression kept a healthy margin (+0.600) on
the identical example -- genuine mechanistic evidence, not just a
citation, for the paper's own finding that logistic regression is the
more robust method.

See `hermes-plugins/local_activation_probe/README.md` for the full
methodology comparison table, all three new experiments with real
numbers, and the paper's own documented failure modes (spurious
correlation with morality, aggregation failures on partially-deceptive
responses) quoted directly.

**Why this matters for the thesis:** this is the white-box counterpart
to Exercise A's black-box monitors -- if a future observability harness
ever needs to catch deception a behavioral monitor can't see (an agent
whose actions look fine but whose internal state doesn't), this is the
mechanism that would do it, and it only works at all on models you can
actually load the weights of.

### B2. `hermes-plugins/observability_bridge/` -- tool-call activity logger

An earlier, simpler Hermes plugin logging tool-call activity for the
rule-based-approver thesis Exercise A builds toward -- appends a
structured JSONL record of every tool call for a downstream correlator
to diff against an independent kernel-level event log (AgentSight).
Observe-only: never blocks, modifies, or approves.

### B3. `docker-sandbox/` -- running Hermes itself inside Docker, with a real, logged architecture decision trail

Explores containerized/sandboxed execution options for a Hermes agent
(rather than the default native-process execution) as a concrete step
toward the observability-harness thesis: an agent that can't escape its
own sandbox is a precondition for trusting any monitor built around it --
this applies equally to the behavioral monitors in Exercise A and the
activation probe in B1.

`docker-sandbox/docs/ARCHITECTURE.md` and `RISKS.md` capture the design
reasoning; `docker-sandbox/docs/VERIFICATION.md` is the full session-log
of what was actually run and checked (including one architecture
decision that was revisited and corrected after further investigation --
kept in the log rather than silently edited out). `docker-sandbox/compose/`
has the actual `docker-compose.yml`; `docker-sandbox/probe_sidecar/` is a
sketch for wiring B1's activation-probe plugin into a sidecar container
rather than running in-process.
