## 7. v4 (FINAL iteration): ~2,000 training examples

Last dataset scale-up in this series. 1,980 training examples (up from
630 in v3, 240 in v2) across 60 tasks, 70 drift subjects, and larger
action-template pools per category.

**Held-out set**: 1,080 examples (up from 360), built the same way as
v3 -- from 18 drift subjects with zero training exposure at all (not
just new phrasings of subjects already seen).

**Result: 1058/1080 (98.0%) held-out drift catch rate** -- up from 95.6%
(v3) and 45.8% (v2). Diminishing returns are visible and expected
(45.8% -> 95.6% -> 98.0% as training data roughly tripled each step) --
consistent with a real, converging generalization curve, not noise.

**Remaining failures, both explainable, not random**: `'AAPL stock
price'` (0% via `web_search`, 86% via `read_file`) and `'moving company
quotes'` (0% via `web_search`, 73% via `read_file`) are the only
imperfect subjects. Both plausibly read as more work-adjacent/ambiguous
than the rest of the held-out set (a stock price could be finance-task
adjacent; "quotes" could be mistaken for a documentation/citation task)
-- the same pattern flagged in v3's "unread emails" case. This looks like
a real, stable edge in the model's decision boundary around
plausibly-work-adjacent personal topics, not overfitting noise -- worth
noting as a genuine, still-present limitation rather than claiming a
clean 100%.

## Full iteration history (v1 -> v4)

| Version | Training examples | Held-out examples | Held-out catch rate |
|---|---|---|---|
| v1 (original) | 160 | 4 (ad hoc, not a systematic held-out set) | 4/4 (100%, but too small to be meaningful) |
| v2 | 240 | 72 | 45.8% |
| v3 | 630 | 360 | 95.6% |
| v4 (final) | 1,980 | 1,080 | **98.0%** |

Each step used a STRICTER held-out methodology than the last (v2: new
sentences about seen-ish topics; v3/v4: entirely unseen subjects held out
before any examples were generated), so the improving numbers are not an
artifact of an easier test -- if anything, the bar got harder each time.

**Final, corrected conclusion** (superseding the "classifier can't
generalize" claim in DIAGNOSTIC_RESULTS.md): a small, cheap LoRA
fine-tune on DistilBERT CAN reach ~98% generalization to genuinely novel
semantic-drift patterns -- but it needed roughly 8x more training data
than the original afternoon-scale exercise to get there, and even at
that scale retains a narrow, identifiable weakness around plausibly
work-adjacent personal topics. The LLM judge's practical advantage isn't
"the classifier can't work" (it can) -- it's needing zero training data
construction effort and having no equivalent blind spot for topics that
are genuinely ambiguous by nature, which is the harder problem no amount
of synthetic data cleanly solves.

Code: `large_dataset_v4.py`, `retrain_v4_final.py`. Full run log:
`retrain_v4_run_output.log`.
