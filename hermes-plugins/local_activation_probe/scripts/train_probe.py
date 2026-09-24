"""
train_probe.py — train a linear deception/misalignment probe on a local
open-weight model's activations.

Usage:
    python scripts/train_probe.py \
        --model Qwen/Qwen3-0.6B \
        --data examples.jsonl \
        --layer 12 \
        --method logistic_regression \
        --out probes/my_probe.json

Data format (examples.jsonl), one JSON object per line:
    {"text": "...", "label": 1}   # label: 1 = deceptive/misaligned example, 0 = honest/aligned
    {"text": "...", "label": 0}
    ...

Implements TWO probe-fitting methods, matching Apollo Research's
"Detecting Strategic Deception Using Linear Probes" (arXiv:2502.03407),
Section 3.1 / Appendix D.1:

  - difference_of_means: direction = normalize(mean(pos) - mean(neg)).
    The simpler baseline the paper tested and found slightly weaker
    (at distinguishing deceptive from CONTROL responses specifically).
  - logistic_regression (DEFAULT, matches the paper's primary/mainline
    method): L2-regularized logistic regression fit via full-batch
    gradient descent in plain torch (no scikit-learn dependency, so the
    fitting code stays auditable in ~15 lines). Regularization
    coefficient (--l2, default 10.0) follows the paper's Appendix D.3
    finding that "λ = 10 [is] a reasonable compromise" — note the
    paper's exact regularization convention isn't reproduced (they
    don't publish their loss formula), so treat our λ as our own
    convention with the same order of magnitude, not a literal match.

Both methods, matching the paper's Section 3 methodology:
  - NORMALIZE activations (zero mean / unit variance, computed from the
    training set) before fitting, and store the normalization stats in
    the probe file so inference applies the identical transform.
  - Train on PER-TOKEN activations, not per-example. Every token in an
    example's text is a training point labeled with that example's
    label (Section 3: probes are applied per-token; aggregation to a
    response-level score happens separately, see Appendix D.4).

Layer default is unset (must pass --layer explicitly) rather than -1
(last layer) or 22 (the paper's layer, tuned for Llama-3.3-70B and NOT
guaranteed to transfer to other models/architectures — see
scripts/sweep_layers.py to pick a layer empirically for your own model).

IMPORTANT: A probe trained here is only meaningful for the SAME model
it was trained on (same architecture, same layer). Do not reuse a probe
across different models — see this plugin's README, "Model-agnostic ≠
probe-agnostic" section.
"""

import argparse
import json
import sys

import torch
from nnsight import LanguageModel


def load_examples(path: str) -> list[dict]:
    examples = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            examples.append(json.loads(line))
    return examples


def extract_all_token_activations(model, text: str, layer: int) -> torch.Tensor:
    """Returns activations for EVERY token position: shape [T, D]."""
    with model.trace(text):
        layer_out = model.model.layers[layer].output
        saved = layer_out.save()
    tensor = saved[0] if isinstance(saved, tuple) else saved
    if tensor.dim() == 3:
        tensor = tensor[0]  # drop batch dim -> [T, D]
    return tensor.detach()


def fit_logistic_regression(
    X: torch.Tensor, y: torch.Tensor, l2: float, lr: float = 0.5, epochs: int = 1000
) -> tuple[torch.Tensor, float]:
    """Full-batch gradient descent, L2-regularized logistic regression.
    X: [N, D] normalized features. y: [N] in {0., 1.}.
    Loss = BCEWithLogits(Xw+b, y) + (l2 / N) * ||w||^2
    Plain torch, no scikit-learn — keeps this auditable in a few lines
    while implementing the paper's actual primary method (not a
    difference-of-means approximation of it)."""
    n, d = X.shape
    X = X.float()
    y = y.float()
    w = torch.zeros(d, requires_grad=True)
    b = torch.zeros(1, requires_grad=True)
    opt = torch.optim.Adam([w, b], lr=lr)
    loss_fn = torch.nn.BCEWithLogitsLoss()
    for _ in range(epochs):
        opt.zero_grad()
        logits = X @ w + b
        loss = loss_fn(logits, y) + (l2 / n) * (w * w).sum()
        loss.backward()
        opt.step()
    return w.detach(), float(b.detach().item())


def fit_difference_of_means(X: torch.Tensor, y: torch.Tensor) -> tuple[torch.Tensor, float]:
    pos = X[y == 1]
    neg = X[y == 0]
    pos_mean = pos.mean(dim=0)
    neg_mean = neg.mean(dim=0)
    direction = pos_mean - neg_mean
    direction = direction / direction.norm()
    pos_proj = float((pos_mean * direction).sum())
    neg_proj = float((neg_mean * direction).sum())
    bias = -(pos_proj + neg_proj) / 2
    return direction, bias


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="HuggingFace model name or local path")
    ap.add_argument("--data", required=True, help="Path to labeled examples.jsonl")
    ap.add_argument("--layer", type=int, required=True, help="Layer index to extract activations from (no default — pick via scripts/sweep_layers.py)")
    ap.add_argument("--out", required=True, help="Output path for probe JSON")
    ap.add_argument("--device", default="cpu", help="Device — CPU strongly recommended, see plugin README")
    ap.add_argument(
        "--method", default="logistic_regression",
        choices=["logistic_regression", "difference_of_means"],
        help="Probe fitting method. logistic_regression (default) matches the paper's "
             "primary/best-performing method (Appendix D.1). difference_of_means is the "
             "simpler baseline the paper found slightly weaker.",
    )
    ap.add_argument("--l2", type=float, default=10.0, help="L2 regularization coefficient for logistic_regression (paper's Appendix D.3 default: 10.0)")
    args = ap.parse_args()

    if args.device != "cpu":
        print(
            "WARNING: non-CPU device requested. NNsight on MPS (Apple Silicon) "
            "is confirmed to segfault on at least one model family as of "
            "nnsight 0.7.0 / torch 2.14 (2026-09-24). Proceed at your own risk.",
            file=sys.stderr,
        )

    print(f"Loading model {args.model} on {args.device}...")
    model = LanguageModel(args.model, device_map=args.device)

    examples = load_examples(args.data)
    print(f"Loaded {len(examples)} labeled examples")

    all_tokens, all_labels = [], []
    for i, ex in enumerate(examples):
        acts = extract_all_token_activations(model, ex["text"], args.layer)  # [T, D]
        all_tokens.append(acts)
        all_labels.append(torch.full((acts.shape[0],), float(ex["label"])))
        if (i + 1) % 10 == 0:
            print(f"  processed {i + 1}/{len(examples)}")

    X = torch.cat(all_tokens, dim=0)  # [total_tokens, D]
    y = torch.cat(all_labels, dim=0)  # [total_tokens]
    print(f"Training on {X.shape[0]} token-level activations ({int(y.sum().item())} positive, {int((1 - y).sum().item())} negative)")

    if y.sum() == 0 or (1 - y).sum() == 0:
        print("ERROR: need at least one example of each class (label 0 and label 1)", file=sys.stderr)
        sys.exit(1)

    # Normalize: zero mean / unit variance over the training set, matching
    # the paper's Section 3 preprocessing. Stats are stored in the probe
    # so inference applies the identical transform. Cast to float32 —
    # model activations often come back as bfloat16, which torch won't
    # silently mix with float32 in matmuls/optimizers.
    X = X.float()
    mean = X.mean(dim=0)
    std = X.std(dim=0) + 1e-6  # avoid div-by-zero on constant dims
    X_norm = (X - mean) / std

    if args.method == "logistic_regression":
        direction, bias = fit_logistic_regression(X_norm, y, l2=args.l2)
    else:
        direction, bias = fit_difference_of_means(X_norm, y)

    probe = {
        "direction": direction.tolist(),
        "bias": bias,
        "normalize": {"mean": mean.tolist(), "std": std.tolist()},
        "aggregation": "mean_all_tokens",
        "meta": {
            "status": f"TRAINED — {args.method} linear probe",
            "trained_for_model": args.model,
            "layer": args.layer,
            "hidden_dim": direction.shape[0],
            "num_examples": len(examples),
            "num_positive_examples": int(y.sum().item()),
            "num_negative_examples": int((1 - y).sum().item()),
            "num_training_tokens": X.shape[0],
            "method": args.method,
            "l2": args.l2 if args.method == "logistic_regression" else None,
        },
    }

    with open(args.out, "w") as f:
        json.dump(probe, f, indent=2)

    print(f"Wrote probe to {args.out}")
    print(
        "IMPORTANT: this probe has NOT been validated on held-out data. "
        "Before trusting it, run scripts/validate_probe.py against examples "
        "the probe never saw during training."
    )


if __name__ == "__main__":
    main()
