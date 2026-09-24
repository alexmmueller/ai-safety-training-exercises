# AI Safety Training Exercises

Two exercises for catching an AI agent doing something it shouldn't:
**Exercise A** monitors agent behavior from the outside (black-box);
**Exercise B** reads a model's internal activations from the inside
(white-box). Independent of each other.

---

## Exercise A: Black-box behavioral monitoring

Deterministic rules vs. a fine-tuned classifier vs. a prompted LLM
judge, tested against synthetic on-task/off-task agent trajectories.

**Classifier iteration arc (A2, A4-A7):**

| Version | Training examples | Held-out drift catch rate | Doc |
|---|---|---|---|
| v1 | 160 | not measured on drift | A2 |
| v2 | 240 | 45.8% (72 held-out) | `ontask-classifier/RETRAIN_RESULTS.md` |
| v2 diagnostic | (same model) | 46.3% (216 held-out) | `ontask-classifier/DIAGNOSTIC_RESULTS.md` |
| v3 | 630 | 95.6% (360 held-out) | `ontask-classifier/V3_RESULTS.md` |
| v4 (final) | 1,980 | **98.0%** (1,080 held-out) | `ontask-classifier/V4_RESULTS.md` |

Read `V4_RESULTS.md` for the full table and final numbers. Other docs
kept as-is with inline corrections noted.

### A1. `boolq-eval/` -- Inspect AI eval infra

Ran `inspect_evals`' `boolq` benchmark against a local model
(`qwen2.5:3b` via Ollama), using the same Inspect AI framework behind
the tool-call approval bugs (inspect_ai#5133, #5132) already reproduced
and reported elsewhere.

**Result:** 90% accuracy (10 samples, stderr 0.10). Log in `logs/`.

**Reproduce:**
```bash
pip install inspect_ai inspect_evals openai
ollama pull qwen2.5:3b && ollama serve &
cd boolq-eval && python run_boolq.py
```

### A2. `ontask-classifier/` -- v1 LoRA on/off-task classifier

LoRA adapter (r=8, alpha=16) on `distilbert-base-uncased`, classifying
`(task instruction, agent action)` pairs as on-task (1) or
off-task/suspicious (0). 160 synthetic examples: 10 agent tasks, each
with genuine on-task actions and off-task actions modeled on the
OpenAI/Hugging Face incident's actual failure pattern (credential
exfiltration, unrelated network access, hidden-channel coordination).
739,586 trainable params / 67.7M total (1.09%). Apple M5 GPU (MPS), 6
epochs, ~4.5s training time.

**Result:** 93.75% held-out accuracy, F1 0.957. 4/4 correct on a small
sanity set of genuinely novel (task, action) pairs.

This is v1 of four iterations (v2-v4: A4-A7) -- synthetic data,
single-line actions, 160 examples, no LLM-judge baseline yet (A3).

**Reproduce:**
```bash
pip install torch transformers peft accelerate datasets scikit-learn
cd ontask-classifier && python finetune_ontask_classifier.py
```

### A3. `monitor-comparison/` -- deterministic rules vs classifier vs LLM judge

See `monitor-comparison/README.md` for the full writeup.

**Result:** deterministic approver and v1 classifier both catch 5/7
off-task trajectories for free (including the #5133 fragmentation case,
via real history reassembly) -- both miss 2 "subtle drift" cases with
no attack signature. A prompted LLM judge (qwen2.5:14b-instruct, local)
catches 7/7, at the cost of a live model call per decision. A hybrid
(deterministic first, escalate to judge on no match) matches the
judge's 100% while cutting judge calls 42%.

**Reproduce:**
```bash
git clone https://github.com/alexmmueller/inspect-deterministic-approver ~/oss/inspect-deterministic-approver
pip install -e ~/oss/inspect-deterministic-approver
ollama pull qwen2.5:14b-instruct
cd monitor-comparison
python compare_monitors.py          # 3-way comparison
python compare_monitors_hybrid.py   # + hybrid escalation, judge-call count
```

### A4. Retrain v2 -- targeting the semantic-drift gap

See `ontask-classifier/RETRAIN_RESULTS.md`. Retrained on an expanded
dataset including drift negatives, measured on a held-out drift set
never seen in training.

**Result:** 33/72 (45.8%) held-out drift catch rate, up from 0%.

**Reproduce:** `cd ontask-classifier && python retrain_with_drift.py`

### A5. Diagnostic test -- theory revised

See `ontask-classifier/DIAGNOSTIC_RESULTS.md`. Tested whether v2 was
keying on tool name as a shortcut (same content, different tool
wrappers) plus a larger 216-example held-out set.

**Result:** near-random, bimodal behavior on novel phrasing -- not one
clean, fixable shortcut.

**Reproduce:** `cd ontask-classifier && python diagnostic_and_expanded_test.py`

### A6. v3 -- scaling training data

See `ontask-classifier/V3_RESULTS.md`. 630 training examples (2.6x v2).

**Result:** 95.6% (344/360) held-out catch rate, up from 45.8%.

**Reproduce:** `cd ontask-classifier && python retrain_v3_large.py`

### A7. v4 (final) -- ~2,000 training examples

See `ontask-classifier/V4_RESULTS.md` for the full table. 1,980
training examples (up from 630).

**Result:** 1058/1080 (98.0%) held-out drift catch rate. Two residual,
explainable failures remain (work-adjacent-sounding subjects).

**Comparison to LLM judge (A3):** classifier accuracy matches the
judge's, using ~8x more training data than v1's original scale; the
judge needs no training-data construction but costs a live model call
per decision.

**Reproduce:** `cd ontask-classifier && python retrain_v4_final.py`

**Environment (A1-A7):** Python 3.11. `boolq-eval` needs `inspect_ai`,
`inspect_evals`, `openai` (for Ollama's OpenAI-compatible API).
`ontask-classifier`/`monitor-comparison` need `torch`, `transformers`,
`peft`, `accelerate`, `datasets`, `scikit-learn`. Each classifier script
saves its own LoRA adapter to `/tmp/ontask_classifier_lora*` (see each
script's `SAVE_DIR`/`ADAPTER_DIR`) -- run them in order (A2 -> A4 -> A5
-> A6 -> A7) since later scripts load the previous adapter.

---

## Exercise B: White-box activation probing

Reads a local open-weight model's internal activations live, during
real agent use, and scores them against a linear probe for
deception/misalignment signals.

### B1. `hermes-plugins/local_activation_probe/` -- deception probe, wired into a Hermes plugin

Implements the mainline method of Apollo Research's ["Detecting
Strategic Deception Using Linear Probes"](https://arxiv.org/abs/2502.03407)
(arXiv:2502.03407, read in full -- see the plugin's own README for exact
quotes and section references): logistic regression, per-token
normalization, mean-over-all-tokens aggregation. Model-agnostic and
probe-agnostic -- point it at any HuggingFace model, train your own
probe.

**New experiment:** out-of-distribution test across five domains the
probe never trained on (logistics, healthcare, aviation, weather,
finance). Difference-of-means nearly failed on a held-out finance
example (score -1.494, close to crossing into "honest") while logistic
regression held a clean margin (+0.600) on the same example --
mechanistic evidence for the paper's own finding that logistic
regression is the more robust method.

**Reproduce:**
```bash
uv venv --python 3.12 ~/.venv-probe-test && source ~/.venv-probe-test/bin/activate
uv pip install nnsight transformers torch

cd hermes-plugins/local_activation_probe
hermes plugins doctor . --ci                                  # sanity check

python scripts/sweep_layers.py --model Qwen/Qwen3-0.6B \
  --data examples/tiny_example.jsonl --layers 4 8 12 16 20 24 -1

python scripts/train_probe.py --model Qwen/Qwen3-0.6B \
  --data examples/tiny_example.jsonl --layer -1 \
  --method logistic_regression --out probes/my_probe.json

python scripts/validate_probe.py --model Qwen/Qwen3-0.6B \
  --probe probes/my_probe.json --data examples/tiny_held_out.jsonl --layer -1

# out-of-distribution test:
python scripts/validate_probe.py --model Qwen/Qwen3-0.6B \
  --probe probes/my_probe.json --data examples/ood_generalization_test.jsonl --layer -1
```

Full methodology comparison table and all experiment numbers:
`hermes-plugins/local_activation_probe/README.md`.

### B2. `hermes-plugins/observability_bridge/` -- tool-call activity logger

Observe-only Hermes plugin, appends a JSONL record of every tool call
for a downstream correlator to diff against an independent
kernel-level event log (AgentSight). Never blocks, modifies, or
approves.

**Reproduce:** `hermes plugins doctor hermes-plugins/observability_bridge --ci`

### B3. `docker-sandbox/` -- running Hermes inside Docker

Architecture/risk docs and a compose skeleton for containerized Hermes
execution. `docker-sandbox/docs/ARCHITECTURE.md` and `RISKS.md` cover
the design; `docker-sandbox/docs/VERIFICATION.md` logs what's actually
been run and checked. `docker-sandbox/probe_sidecar/` is a sketch for
running B1 as a sidecar container instead of in-process.

**Reproduce:** `cd docker-sandbox/compose && docker compose up` --
unverified/skeleton as of `docs/VERIFICATION.md`, check there first.
