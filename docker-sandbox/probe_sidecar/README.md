# Probe sidecar — STATUS: SKELETON ONLY, NOT IMPLEMENTED

This directory is a placeholder. Nothing here runs yet.

## What this is supposed to do

1. Watch the shared-memory / disk path where `vllm-serve`'s
   `extract_hidden_states` writes safetensors files per completion
   (see compose/docker-compose.yml, `HIDDEN_STATES_DIR`).
2. For each new hidden-states file, load the tensor and apply a linear
   probe (weights TBD-vendored from `ApolloResearch/deception-detection`'s
   `example_results/`, or retrained if using a non-Llama model — see
   docs/RISKS.md R5).
3. Write `{completion_id, deception_score, layer, timestamp}` as JSONL to
   the shared log volume. Never blocks, never calls back into Hermes or
   vLLM — pure async observer, per the observe-only phase decision.

## What actually needs to happen before this is real code

- [ ] Decide vLLM-native `extract_hidden_states` vs. NNsight vLLM
      integration as the extraction mechanism (docs/RISKS.md R6) — spike
      both against a single trivial completion first.
- [ ] Vendor or `pip install -e` Apollo's `deception-detection` package,
      confirm `example_results/` actually contains loadable probe weights
      (only verified via GitHub file listing so far, not opened/loaded).
- [ ] Pick a served model (docs/RISKS.md R5/R7) and confirm probe
      compatibility, or accept exploratory-only status and validate with
      a synthetic known-deceptive / known-honest transcript pair before
      trusting any score against real traffic.
- [ ] Write the actual watcher (watchdog/inotify on the hidden-states
      directory, or poll — TBD) and scoring loop.
- [ ] Write `docs/VERIFICATION.md` entries once each piece is confirmed
      working, with real command output pasted in, not just "should work."

## Do not

- Do not present a probe score from this component as a definitive
  deception verdict. Per Apollo's own paper, the underlying method can be
  triggered by deception-*related text* rather than actual deceptive
  intent, and cross-model/cross-distribution generalization is unproven.
  Treat every score as a weighted, unverified signal for a human to look
  at — never as an automated block trigger in this phase.
