## 6. v3: scaling training data 2.6x closes most of the generalization gap

Direct follow-up to the v2 diagnostic finding (45.8% held-out drift catch
rate, near-random/bimodal behavior on novel phrasing, not one fixable
shortcut). Tested the obvious next question: does more data actually fix
it?

**Scale-up**: 630 training examples (up from 240 in v2) across 30 tasks
(up from 12) and ~40 distinct drift subjects (up from 8), built
programmatically from templates to get real phrasing variety rather than
hand-writing each example.

**Held-out set redesigned to be stricter than v2's**: 360 examples built
from 12 drift *subjects* that are completely absent from training --
not just new sentences about topics the model already saw, but subjects
(vintage vinyl records, meditation apps, board game rules, etc.) it has
zero prior exposure to at all.

**Result: 344/360 (95.6%) held-out catch rate** -- up from 45.8% with the
smaller dataset. More data, on this scale of test, substantially closed
the generalization gap that a "smarter loss function" or architecture
change likely wouldn't have fixed on its own -- consistent with the v2
diagnostic conclusion that the original failure was a data-scale problem,
not a specific fixable bug.

**One honest residual failure, not swept under the rug**: the subject
"unread emails" scored 0% (both `web_search` and `read_file` phrasings)
-- the only complete miss in the set. This may be less a model failure
than a labeling judgment call: "checking unread emails" plausibly reads
as more work-adjacent/ambiguous than the other 11 held-out subjects
(horoscopes, vinyl records, dentist reminders), which are unambiguously
personal/off-topic. Worth flagging as a limitation in the label
construction, not just the model, rather than claiming a clean 100%.

**What this changes about the earlier conclusion**: the v2/diagnostic
writeups argued a small classifier "doesn't reliably generalize at all"
and used that as a reason judgment-based monitoring is necessary. The v3
result complicates that a little -- a cheap classifier *can* generalize
well with enough (still synthetic, still cheap to produce) training data.
The more accurate updated claim: a classifier trained on ~240 examples of
one narrow flavor doesn't generalize; ~630 more varied examples gets it
most of the way there. The LLM judge is still valuable as the
zero-training-data option and for genuinely novel failure modes no one
thought to include in a training set -- but "classifier can't work" was
too strong a claim, and this run corrects that.

**Note: this was not the final iteration.** A further scale-up to ~2,000
training examples (v4, see `V4_RESULTS.md`) pushed held-out accuracy to
98.0% and is the final word in this series -- see that doc for the
complete v1-v4 iteration table.

Code: `large_dataset_v3.py`, `retrain_v3_large.py`. Full run log:
`retrain_v3_run_output.log`.
