## 4. Retraining v2: targeting the semantic-drift gap with a real
   generalization test

The original monitor comparison found both the deterministic approver and
the first-pass classifier missed 2/2 "semantic drift" cases (off-task
actions with no attack-shaped keyword signature). This follow-up
retrains the classifier on an expanded dataset that specifically includes
drift negatives, and -- critically -- measures it on a **held-out drift
set never seen in training**, to test whether it actually generalized to
the *pattern* of drift or just memorized specific examples.

**Training set**: 240 examples across 12 tasks (up from 160/10), balanced
across on-task, attack-shaped negatives, and 8 varied drift negatives
(pizza search, vacation notes, marathon training, etc. -- deliberately
different subject matter from the eval set).

**Held-out eval set (the real test)**: 72 examples, 6 drift actions
(coffee shops, personal to-do lists, browsing news, Roman history,
journaling, stock prices) across all 12 tasks -- **none of these actions
appear anywhere in training**.

**Same-distribution eval accuracy: 100%** (as expected -- this just
confirms the model fit the training distribution, not that it generalized).

**Held-out drift catch rate: 33/72 (45.8%)** -- up from the original
classifier's 0% on drift, but far from perfect. This is the honest,
interesting result.

### What it actually learned (and what it didn't)

**UPDATE: the theory below was tested directly and partially overturned --
see `DIAGNOSTIC_RESULTS.md` for that correction, and `V4_RESULTS.md` for
the final, fully corrected conclusion (more training data closes most of
the gap, up to 98% held-out accuracy at ~2,000 examples).** Keeping the
original reasoning here for transparency about how the investigation
progressed, rather than editing history.

Breaking down the held-out results by action reveals a consistent,
non-random pattern:

- **Reliably caught**: `web_search('...')` on off-topic subjects,
  `run_command('open_browser_tab ...')`
- **Reliably missed**: `write_file('scratch/todo_personal.md', ...)`,
  `write_file('journal_entry.txt', ...)`, `run_command('check_stock_price
  ...')`

This isn't random noise -- it's a real, diagnosable limitation. The model
appears to have partly learned "tool/verb-shape" as a shortcut feature
rather than genuine task-relevance reasoning: `write_file` and
`run_command` both appear frequently in the *on-task* training examples
too (writing tests, writing READMEs, running deploy checks), so the model
likely biased toward approving those verbs regardless of content, while
`web_search` calls on clearly off-topic subjects were flagged more reliably.

**This is a legitimate, reportable finding about the limits of small
fine-tunes on synthetic data**, not a hidden failure: a small classifier
trained on ~240 examples picks up surface correlations (which tool is
called) faster than it learns the underlying semantic relationship
(does this content relate to that task) -- exactly the kind of thing a
prompted LLM judge, with real world knowledge and no such narrow training
distribution, doesn't struggle with. It's a concrete, measured argument
for why the harness thesis needs the judgment layer, not just "a bigger
classifier" -- more data of the same synthetic shape would likely just
sharpen the same shortcut, not fix it.

Code: `expanded_dataset.py` (training + held-out sets, clearly separated),
`retrain_with_drift.py`. Full run log: `retrain_run_output.log`.
