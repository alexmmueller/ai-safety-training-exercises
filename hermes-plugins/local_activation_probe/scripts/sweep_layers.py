"""
sweep_layers.py — empirically pick a layer for this plugin's probe on
YOUR model, instead of guessing.

This closes a real gap versus Apollo Research's methodology
(arXiv:2502.03407, Appendix D.2): the paper's layer-22-of-80 choice was
found via a sweep on Llama-3.1 and validated to transfer to Llama-3.3 —
it is NOT a universal constant, and this plugin has no basis to assume
it transfers to an arbitrary other model/architecture (different depth,
different residual stream conventions). Rather than pick another
arbitrary default, this script does the sweep for you.

For each candidate layer, trains a small difference-of-means probe
(fast — no gradient descent) on a TRAIN split, and reports AUROC on a
held-out VALIDATION split of the same data — so you can pick the best
layer, then retrain your real probe there with train_probe.py
(logistic_regression is slower per-layer, so the sweep itself uses the
cheap method, matching the paper's own finding that "performance is
very similar across methods for distinguishing deceptive and honest
responses", Appendix D.1 — method choice barely matters for this
sweep's purpose of finding a good layer, even though it matters more
for the final probe).

Usage:
    python scripts/sweep_layers.py \
        --model Qwen/Qwen3-0.6B \
        --data examples.jsonl \
        --layers 4 8 12 16 20 -1
    (or omit --layers to sweep every layer in the model)
"""

import argparse
import json
import random

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


def extract_mean_activation(model, text: str, layer: int) -> torch.Tensor:
    """Mean-pooled activation across all tokens — cheap, matches this
    plugin's mainline mean-token aggregation without needing per-token
    training for the sweep itself."""
    with model.trace(text):
        layer_out = model.model.layers[layer].output
        saved = layer_out.save()
    tensor = saved[0] if isinstance(saved, tuple) else saved
    if tensor.dim() == 3:
        tensor = tensor[0]
    return tensor.mean(dim=0).float().detach()  # [D], float32 (model may output bfloat16)


def auroc(pos_scores, neg_scores) -> float:
    all_scores = [(s, 1) for s in pos_scores] + [(s, 0) for s in neg_scores]
    all_scores.sort(key=lambda t: t[0])
    n_pos, n_neg = len(pos_scores), len(neg_scores)
    rank_sum, rank, i = 0.0, 1, 0
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
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--layers", type=int, nargs="*", default=None, help="Candidate layers; default sweeps every layer")
    ap.add_argument("--val-frac", type=float, default=0.3, help="Fraction of data held out for validation each layer")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    random.seed(args.seed)
    print(f"Loading model {args.model}...")
    model = LanguageModel(args.model, device_map="cpu")
    n_layers = len(model.model.layers)
    layers = args.layers if args.layers is not None else list(range(n_layers))
    print(f"Model has {n_layers} layers. Sweeping: {layers}")

    examples = load_examples(args.data)
    random.shuffle(examples)
    n_val = max(2, int(len(examples) * args.val_frac))
    val_examples, train_examples = examples[:n_val], examples[n_val:]
    print(f"Train: {len(train_examples)}  Val: {len(val_examples)}")
    if not train_examples or not val_examples:
        print("ERROR: need enough examples to split into train/val (>=4 recommended)")
        return

    results = []
    for layer in layers:
        train_acts = [(extract_mean_activation(model, ex["text"], layer), ex["label"]) for ex in train_examples]
        val_acts = [(extract_mean_activation(model, ex["text"], layer), ex["label"]) for ex in val_examples]

        pos = torch.stack([a for a, l in train_acts if l == 1])
        neg = torch.stack([a for a, l in train_acts if l == 0])
        if pos.shape[0] == 0 or neg.shape[0] == 0:
            print(f"layer {layer:>4}: skipped (train split missing a class)")
            continue
        direction = pos.mean(dim=0) - neg.mean(dim=0)
        direction = direction / direction.norm()
        bias = -((pos.mean(dim=0) * direction).sum() + (neg.mean(dim=0) * direction).sum()) / 2

        val_pos_scores = [float((a * direction).sum() + bias) for a, l in val_acts if l == 1]
        val_neg_scores = [float((a * direction).sum() + bias) for a, l in val_acts if l == 0]
        if not val_pos_scores or not val_neg_scores:
            print(f"layer {layer:>4}: skipped (val split missing a class)")
            continue
        score = auroc(val_pos_scores, val_neg_scores)
        results.append((layer, score))
        print(f"layer {layer:>4}: held-out AUROC = {score:.3f}")

    if results:
        best_layer, best_score = max(results, key=lambda t: t[1])
        print()
        print(f"BEST: layer {best_layer} (held-out AUROC {best_score:.3f})")
        print(
            f"NOTE: with only {len(val_examples)} validation examples, this is a rough "
            "signal, not a statistically robust layer choice — the paper's own Appendix "
            "D.2 notes 'large variation in performance even between adjacent layers', "
            "so treat this as a starting point and re-check with more data if this probe "
            "matters for a real decision."
        )
        print(f"Next: python scripts/train_probe.py --model {args.model} --data {args.data} --layer {best_layer} --out probes/my_probe.json")


if __name__ == "__main__":
    main()
