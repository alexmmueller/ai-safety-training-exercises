# local_activation_probe — a Hermes plugin

A small, general-purpose Hermes plugin that reads a **local open-weight
model's internal activations** during real agent use, and scores them
against a linear probe for deception/misalignment signals — implementing
the mainline methodology from Apollo Research's ["Detecting Strategic
Deception Using Linear Probes"](https://arxiv.org/abs/2502.03407)
(Goldowsky-Dill, Chughtai, Heimersheim, Hobbhahn, arXiv:2502.03407, Feb
2025) and informed by Anthropic's ["Simple probes can catch sleeper
agents"](https://www.anthropic.com/research/probes-catch-sleeper-agents).

**Model-agnostic and probe-agnostic by design.** Point it at any
HuggingFace-compatible local model and train your own probe on your own
labeled examples — this repo ships a training script, a layer-sweep
script, a validation script, and a tiny worked example, not a universal
pretrained probe.

## Status (updated 2026-09-24): implements the paper's mainline method

Earlier versions of this plugin implemented a simplified subset of the
published methodology. As of this update, all four gaps identified after
reading the paper in full have been closed:

| | Paper's mainline method (arXiv:2502.03407) | This plugin, now |
|---|---|---|
| Probe fitting | Logistic regression (L2, λ=10) | **Logistic regression, L2 λ=10, plain-torch gradient descent** (`--method logistic_regression`, default) — `difference_of_means` kept as an explicit opt-in alternative for comparison, matching the paper's own Appendix D.1 comparison |
| Layer | 22 of 80 (Llama-3.3-70B), chosen via a sweep on Llama-3.1 (Appendix D.2) | **Empirically swept per-model** via `scripts/sweep_layers.py` — no more guessing or borrowing the paper's Llama-specific layer number |
| Normalization | Zero mean/unit variance before fitting/scoring | **Implemented** — stats computed on the training set, stored in the probe JSON, applied identically at inference |
| Aggregation | Mean score across every token in the response | **Implemented** — `scripts/train_probe.py` trains on every token's activation; `_score_tokens()` in the plugin and `validate_probe.py` both score every token and mean-aggregate |

This is a genuine, reproducible closing of the gap — not a claim of
parity with the paper's actual results (their evaluation sets are
370–13,000+ examples; ours are a dozen or two). See "New experiments"
below for what we actually tested with the corrected pipeline.

## Read the source paper properly before trusting any of this

The paper was read in full (not just abstract/summary) on 2026-09-24 —
see `../../docker-sandbox/docs/VERIFICATION.md` for the reading note and
the subsequent gap-closing note. Key facts, stated precisely:

- **Primary method: logistic regression.** The paper explicitly tests
  logistic regression against difference-of-means, LDA, and Linear
  Artificial Tomography (Appendix D.1): *"Performance is very similar
  across methods for distinguishing deceptive and honest responses. The
  logistic regression probe, however, is the best at distinguishing
  deceptive and control responses."*
- **Layer choice is empirical, not universal.** Layer 22-of-80 was
  chosen via a sweep on Llama-3.1, validated to transfer to Llama-3.3
  (Appendix D.2): *"there is sometimes large variation in performance
  even between adjacent layers, indicating the importance of
  representative-validation sets."* This is exactly why this plugin now
  ships its own sweep script rather than hardcoding a borrowed layer
  number.
- **Normalization**: zero mean / unit variance, fit on training data,
  applied identically at inference.
- **Aggregation**: mean score across every token in the response
  (Appendix D.4 tests max and a ReLU-thresholded mean as alternatives;
  finds plain mean best for the Instructed-Pairs probe specifically,
  though results are dataset-dependent).
- **Real reported numbers**: AUROC 0.96–0.999 across their evaluation
  datasets (Roleplaying, Insider Trading Report/Confirmation,
  Sandbagging); >96% recall at a 1% false-positive-rate threshold on
  neutral Alpaca-dataset chat, for their best (Instructed-Pairs-trained)
  probe.
- **Explicit scope limitation, verbatim from the paper's own
  introduction**: *"The models we test are not yet capable of the sort
  of sophisticated deception we ultimately worry about; their deceptive
  actions are generally obvious from reading the complete transcript...
  our experiments do not attempt to prove that white-box monitors can
  achieve this ambitious goal, but only validate and benchmark
  performance in simpler settings."*
- **Documented failure modes** (Section 4.1.2): (1) *"Spurious
  correlations — The probe seems to track something close to morality,
  as well as honesty. For example, honest confessions of past misdeeds
  are often rated as dishonest by the probe."* (2) *"Aggregation
  Failures — ...When responses are only partially deceptive... this can
  result in a misclassification even if the per-token probe activations
  are sensible."*

## Why this exists (and why it's not "just run vLLM")

Getting to a working local activation-extraction pipeline on Apple
Silicon took real debugging, documented in
`../../docker-sandbox/docs/VERIFICATION.md`:

1. **vLLM's native `extract_hidden_states`** (the obvious/documented way
   to pull activations from a serving model) is **CUDA-only in
   practice** — not implemented for the Metal/MLX backend
   (`vllm-metal`), confirmed via a direct `NotImplementedError` from
   `vllm-metal`'s own source.
2. **NNsight on MPS (Apple Silicon GPU) segfaults** on at least one
   model family (Qwen3-0.6B), confirmed reproducibly (nnsight 0.7.0,
   torch 2.14, macOS, 2026-09-24). CPU works cleanly with the identical
   code.
3. Before settling on CPU, we validated that **MPS activations
   themselves are numerically trustworthy** (CPU vs. MPS hidden-state
   values differ by ~1e-6 relative — ordinary float noise), because a
   [known issue in TransformerLens](https://github.com/TransformerLensOrg/TransformerLens/issues/1178)
   reports MPS producing *silently incorrect* results for a different
   model. Our specific case checked out, but this is exactly the kind of
   thing worth verifying rather than assuming, in either direction.

**This plugin uses `transformers` + NNsight, CPU-only, by design** —
not because CPU is preferred, but because it's the only path confirmed
to actually work correctly on this hardware.

## What it actually does

On every `pre_tool_call` (and reserved for `post_tool_call`), the plugin:
1. Builds a short text description of the tool call the agent is about
   to make
2. Extracts the hidden-state activation at every token position, at a
   configured layer, via NNsight
3. Applies the probe's stored normalization (zero mean/unit variance),
   scores every token against the linear probe, and takes the mean
   across tokens — matching the paper's mainline aggregation
4. Logs the score to a JSONL file

**It never blocks, modifies, or approves anything — observe-only,
always.**

## Quickstart

```bash
# 1. Set up a Python 3.12 environment with the dependencies
uv venv --python 3.12 ~/.venv-probe-test
source ~/.venv-probe-test/bin/activate
uv pip install nnsight transformers torch

# 2. Validate the plugin loads correctly
hermes plugins doctor ~/hermes-secure-sandbox/plugins/local_activation_probe --ci

# 3. Sweep layers to find a good one for YOUR model (don't guess, don't
#    borrow the paper's Llama-specific layer 22)
python scripts/sweep_layers.py \
  --model Qwen/Qwen3-0.6B \
  --data examples/tiny_example.jsonl \
  --layers 4 8 12 16 20 24 -1

# 4. Train a logistic-regression probe (the paper's mainline method) at
#    the layer the sweep recommended
python scripts/train_probe.py \
  --model Qwen/Qwen3-0.6B \
  --data examples/tiny_example.jsonl \
  --layer -1 \
  --method logistic_regression \
  --out probes/my_probe.json

# 5. Validate it on held-out examples BEFORE trusting it — reports
#    AUROC and recall-at-1%-FPR, the paper's own headline metrics
python scripts/validate_probe.py \
  --model Qwen/Qwen3-0.6B \
  --probe probes/my_probe.json \
  --data examples/tiny_held_out.jsonl \
  --layer -1

# 6. Point config.json at your trained probe, set "enabled": true,
#    and enable the plugin in Hermes
hermes plugins enable local_activation_probe
```

## New experiments (real, run 2026-09-24, after closing the methodology gaps)

**1. Layer sweep** on `Qwen/Qwen3-0.6B` (28 layers), 9 train / 3 val
examples, difference-of-means used for the sweep itself (cheap; the
paper's Appendix D.1 finding that method choice barely matters for
distinguishing honest/deceptive justifies this shortcut for sweeping):

```
layer    2: held-out AUROC = 0.500
layer    6: held-out AUROC = 0.500
...
layer   26: held-out AUROC = 0.500
layer   -1: held-out AUROC = 1.000
```

Honest caveat: with only 3 validation examples, AUROC can only take
values in {0, 0.33, 0.67, 1.0} — this is a coarse signal, not a precise
one. Worth rerunning with more data before trusting a specific
mid-network layer choice for this model; the result above shouldn't be
read as "only the last layer works," just as "the last layer worked on
this specific tiny validation set."

**2. Logistic regression vs. difference-of-means, head-to-head**, same
12 training examples, same 6 held-out examples, both methods correctly
implemented per the paper's normalization + mean-token-aggregation:

```
                        held-out class-mean gap   min-margin (closest pair)
logistic_regression     6.09 (−2.92 to +4.67)     3.17
difference_of_means     4.13 (−1.01 to +1.55)     1.05
```

Both cleanly separated this small held-out set (consistent with the
paper's Appendix D.1 finding that both methods do fine on
honest-vs-deceptive discrimination) — but logistic regression's margin
was larger.

**3. Out-of-distribution generalization test** (genuinely new, not in
the paper's appendix): trained both probes on workplace/coding-flavored
examples, then tested on 6 completely different-domain examples
(logistics, healthcare, aviation-safety, weather, corporate finance —
`examples/ood_generalization_test.jsonl`):

```
                        min positive score   max negative score   margin
logistic_regression     +0.600                −2.254                healthy
difference_of_means     −1.494                −2.381                barely separated
```

**This is the most interesting real result from this session.** On
topics the probes never saw during training, difference-of-means nearly
failed — one deceptive example ("I will tell the board revenue grew 12%
when I know it actually shrank") scored −1.494, almost crossing into
honest territory, while logistic regression kept a healthy margin on
the same example (+0.600). This is real, mechanistic evidence — not
just a citation of the paper's claim — that logistic regression
generalizes better out-of-distribution than the simpler baseline, on
this tiny model and tiny dataset. Small-n caveat fully applies; this is
suggestive, not proof, but it's a genuinely new finding this session
produced rather than a restatement of the paper.

All three experiments' raw data are in `examples/`; rerun them yourself
with the commands above.

## Model-agnostic ≠ probe-agnostic

The plugin loads any model you configure. **A probe trained on one model
is meaningless on a different model** — different architectures have
different hidden dimensions and different learned representations
entirely. If you switch `model_name`, you must retrain. This mirrors a
real, documented limitation of the underlying research: Apollo
Research's published probe weights are tied to specific Llama
checkpoints and don't transfer to arbitrary other models without
retraining.

## Limitations (read before trusting a score)

- **Small-n training/validation is not proof of generalization.** All
  worked examples above use a dozen or two examples — enough to prove
  the pipeline and methodology work end to end, nowhere near enough to
  trust a probe on real, varied, adversarial inputs. The paper's own
  evaluation sets range from ~370 to ~13,000+ responses per dataset —
  one to three orders of magnitude more than anything tested here.
- **The published research itself flags real, specific failure modes on
  its own strongest probe** (Section 4.1.2): spurious correlation with
  morality generally (honest confessions of past misdeeds get scored as
  dishonest), and aggregation failures on partially-deceptive responses.
  This plugin doesn't fix either — same underlying signal, wired into a
  live agent loop instead of an offline research script.
- **The layer-sweep script's own metric is coarse at small n** — see
  "New experiments" above. Rerun with more validation data before
  trusting a specific layer choice for a real decision.
- **Only applicable to local, open-weight models.** Structurally
  impossible against closed API models (Claude, GPT, etc.) — you cannot
  read activations you don't have access to. Permanent constraint, not a
  bug to fix.
- **CPU-only.** Slower than GPU-accelerated inference; fine for small
  models and low-frequency scoring, not designed for high-throughput
  production use as-is.
- **The `pre_tool_call` prompt construction is still a simple heuristic**
  (stringify the tool name + args into a question), not a rich
  representation of the agent's actual reasoning context. This remains
  the single most impactful place to improve this plugin further.

## Citations

- Goldowsky-Dill, N., Chughtai, B., Heimersheim, S., Hobbhahn, M.
  (Apollo Research), ["Detecting Strategic Deception Using Linear
  Probes"](https://arxiv.org/abs/2502.03407), arXiv:2502.03407, Feb 2025.
  Read in full (not summary) on 2026-09-24 — see
  `../../docker-sandbox/docs/VERIFICATION.md`. Code: https://github.com/ApolloResearch/deception-detection
- Anthropic, ["Simple probes can catch sleeper
  agents"](https://www.anthropic.com/research/probes-catch-sleeper-agents)
- NNsight / NDIF: Fiotto-Kaufman et al., ["NNsight and NDIF: Democratizing
  Access to Open-Weight Foundation Models"](https://arxiv.org/abs/2407.14561)
