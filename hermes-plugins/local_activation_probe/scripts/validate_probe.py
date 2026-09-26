"""
validate_probe.py — check a trained probe against held-out labeled
examples (examples the probe did NOT see during training).

Usage:
    python scripts/validate_probe.py \
        --model Qwen/Qwen3-0.6B \
        --probe probes/my_probe.json \
        --data held_out_examples.jsonl \
        --layer 12

Scores each held-out example by extracting activations at EVERY token
position, applying the probe's stored normalization, scoring each
token, then taking the MEAN score across all tokens in the response —
matching Apollo Research's mainline aggregation method (arXiv:2502.03407,
Section 4.1.2 / Appendix D.4: "We normally take the mean probe-score
over all tokens in the model's response").

Prints each example's true label and probe score, plus AUROC and recall
at 1% FPR when there are enough examples for those metrics to be
meaningful (the paper's own headline numbers), falling back to a simple
mean-separation summary for small n where the paper's metrics would be
misleadingly precise.
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
            if line:
                examples.append(json.loads(line))
    return examples


def extract_all_token_activations(model, text: str, layer: int) -> torch.Tensor:
    with model.trace(text):
        layer_out = model.model.layers[layer].output
        saved = layer_out.save()
    tensor = saved[0] if isinstance(saved, tuple) else saved
    if tensor.dim() == 3:
        tensor = tensor[0]
    return tensor.detach()


def score_response(acts: torch.Tensor, probe: dict) -> float:
    """acts: [T, D] per-token activations. Normalizes using the probe's
    stored training-set stats, scores every token, returns the mean —
    matching the paper's mainline aggregation."""
    acts = acts.float()  # model activations often come back as bfloat16
    if "normalize" in probe:
        mean = torch.tensor(probe["normalize"]["mean"])
        std = torch.tensor(probe["normalize"]["std"])
        acts = (acts - mean) / std
    direction = torch.tensor(probe["direction"])
    bias = probe.get("bias", 0.0)
    per_token_scores = acts @ direction + bias  # [T]
    return float(per_token_scores.mean().item())


def compute_auroc(pos_scores: list[float], neg_scores: list[float]) -> float:
    """AUROC via the Mann-Whitney U statistic — no sklearn dependency.
    Ties are handled with the standard mid-rank correction."""
    all_scores = [(s, 1) for s in pos_scores] + [(s, 0) for s in neg_scores]
    all_scores.sort(key=lambda t: t[0])
    n_pos, n_neg = len(pos_scores), len(neg_scores)
    rank_sum = 0.0
    i = 0
    rank = 1
    while i < len(all_scores):
        j = i
        while j < len(all_scores) and all_scores[j][0] == all_scores[i][0]:
            j += 1
        avg_rank = (rank + (rank + (j - i) - 1)) / 2
        for k in range(i, j):
            if all_scores[k][1] == 1:
                rank_sum += avg_rank
        rank += (j - i)
        i = j
    u = rank_sum - n_pos * (n_pos + 1) / 2
    return u / (n_pos * n_neg)


def recall_at_fpr(pos_scores: list[float], neg_scores: list[float], target_fpr: float = 0.01) -> float:
    """Recall (true positive rate) at a fixed false-positive-rate
    threshold on the negative-class scores — the paper's other headline
    metric (evaluated there against a large neutral chat dataset, not
    reproduced at that scale here)."""
    if not neg_scores:
        return float("nan")
    sorted_neg = sorted(neg_scores, reverse=True)
    idx = max(0, int(len(sorted_neg) * target_fpr) - 1)
    threshold = sorted_neg[idx] if sorted_neg else float("inf")
    if not pos_scores:
        return float("nan")
    return sum(1 for s in pos_scores if s > threshold) / len(pos_scores)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--probe", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--layer", type=int, required=True)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    with open(args.probe) as f:
        probe = json.load(f)

    print(f"Loading model {args.model} on {args.device}...")
    model = LanguageModel(args.model, device_map=args.device)

    examples = load_examples(args.data)
    pos_scores, neg_scores = [], []

    for ex in examples:
        acts = extract_all_token_activations(model, ex["text"], args.layer)
        s = score_response(acts, probe)
        (pos_scores if ex["label"] == 1 else neg_scores).append(s)
        print(f"true_label={ex['label']}  score={s:+.3f}  n_tokens={acts.shape[0]}  text={ex['text'][:60]!r}")

    if not pos_scores or not neg_scores:
        print("Need at least one example of each label to compute separation.", file=sys.stderr)
        return

    pos_mean = sum(pos_scores) / len(pos_scores)
    neg_mean = sum(neg_scores) / len(neg_scores)
    print()
    print(f"Class 1 (label=1) mean score: {pos_mean:+.3f}  (n={len(pos_scores)})")
    print(f"Class 0 (label=0) mean score: {neg_mean:+.3f}  (n={len(neg_scores)})")

    separated = (pos_mean > neg_mean and min(pos_scores) > max(neg_scores)) or \
                (neg_mean > pos_mean and min(neg_scores) > max(pos_scores))
    if separated:
        print("Classes are CLEANLY separated on this held-out set (no score overlap).")
    else:
        print(
            "WARNING: score ranges OVERLAP between classes on this held-out set. "
            "This probe's signal is not reliable as-is — do not trust it for "
            "real decisions without more training data and investigation."
        )

    # AUROC / recall-at-1%-FPR are the paper's own headline metrics
    # (Section 4). We compute them here for transparency, but with n in
    # the single/double digits (typical for a quick local test) they are
    # NOT comparable to the paper's numbers, which used 370-13,000+
    # examples per dataset. Report them anyway, labeled honestly.
    auroc = compute_auroc(pos_scores, neg_scores)
    recall = recall_at_fpr(pos_scores, neg_scores, target_fpr=0.01)
    print()
    print(f"AUROC: {auroc:.3f}  (paper's reported range on their eval sets: 0.96-0.999 — "
          f"NOT directly comparable at this sample size, n={len(pos_scores) + len(neg_scores)})")
    print(f"Recall at 1% FPR: {recall:.3f}  (paper's reported: >0.96 on their largest eval sets — "
          f"with n={len(neg_scores)} negatives here, the 1% FPR threshold itself is barely defined)")


if __name__ == "__main__":
    main()
