# Hermes Secure Sandbox — Architecture

Status: **design + scaffolding**, not yet run end-to-end. Nothing in this repo
has been verified against real hardware. Treat every claim below as a design
target until a corresponding component has been executed and its output
pasted into `docs/VERIFICATION.md` (create that file the first time something
actually runs).

## Goal

A self-contained, hardware-agnostic execution environment for a Hermes agent
that provides three independent layers of observability, deliberately kept
separate so that no layer's failure silently degrades another:

1. **Kernel-level boundary observability** (AgentSight, eBPF) — sees real
   syscalls/network/file events regardless of what the agent or Hermes claims
   happened. Model-agnostic; works with any LLM backend.
2. **Application-level policy** (Hermes's own `pre_tool_call` hook + Tirith) —
   fast, in-process, already shipped by Hermes. Known historical bug: block
   verdicts were silently discarded until v2026.4.16 (hermes-agent#41045).
   Treat this layer as best-effort, not a guarantee.
3. **Mechanistic/activation observability** (linear probes on residual-stream
   activations, à la Apollo Research's deception probes) — only possible
   because the model is open-weight and served locally inside this sandbox.
   This is the layer that has no equivalent when talking to a closed API
   model (Claude/GPT via API never expose activations).

Layers 1 and 3 are boundary-enforceable in the "Containment Verification"
sense (arXiv:2605.09045) or at least independently observable; layer 2 is a
convenience/fast-path layer riding on the agent framework's own honesty.
**Do not present layer 3's probe score as a guarantee.** Per Apollo's own
paper, probes can be triggered by "deception-related text" rather than
actual deceptive intent, and generalization outside the training
distribution is unproven. Treat it as a weighted signal, not a verdict.

## Current phase: OBSERVE ONLY

Per explicit decision: the probe signal and AgentSight events are **async,
logged and alerted, not blocking**. Nothing in this design pauses a tool
call pending a probe score. This is intentional — first prove the signal is
meaningful (does the probe score actually correlate with anything real, in
practice, on this agent's traffic) before trusting it to gate execution.
Promoting to blocking mode is a deliberate, separate decision — see
`docs/PROMOTION_TO_BLOCKING.md` (not yet written; write it only after
observe-mode has produced real logged data to evaluate).

## Component diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ Linux VM / host (kernel required for eBPF — Docker Desktop LinuxKit  │
│ VM on macOS is a candidate but UNVERIFIED, see RISKS.md)             │
│                                                                       │
│  ┌───────────────────────┐                                          │
│  │ agentsight-sidecar     │  privileged container                   │
│  │ (eBPF, host PID ns)    │  scoped to hermes-agent's cgroup         │
│  │ → JSONL event log      │  writes to shared, agent-unwritable      │
│  └───────────┬───────────┘  volume: /var/log/sandbox/agentsight.jsonl│
│              │                                                       │
│  ┌───────────▼───────────┐   ┌────────────────────────────────────┐ │
│  │ hermes-agent           │──▶│ vllm-serve                         │ │
│  │ (docker terminal        │   │ open-weight model                  │ │
│  │  backend; NOT the same  │   │ --speculative_config               │ │
│  │  container as this      │   │   extract_hidden_states            │ │
│  │  compose's other        │   │ --kv_transfer_config                │ │
│  │  services — see below)  │   │   ExampleHiddenStatesConnector     │ │
│  │                          │   │ OpenAI-compatible :8000/v1         │ │
│  │  model.base_url ─────────┼──▶│ (Hermes model.provider: custom)    │ │
│  │  plugins/observability_ │   └──────────────┬─────────────────────┘ │
│  │  bridge (pre_tool_call, │                  │ hidden_states.safetensors
│  │  post_tool_call hooks,  │                  │ per completion
│  │  OBSERVE ONLY — never   │                  ▼                       │
│  │  returns block/modify)  │   ┌────────────────────────────────────┐ │
│  └──────────────────────────┼──▶│ probe-sidecar                     │ │
│                              │   │ loads Apollo linear-probe weights │ │
│                              │   │ scores each completion's hidden   │ │
│                              │   │ states → deception_score          │ │
│                              │   │ writes to shared JSONL             │ │
│                              │   └──────────────┬─────────────────────┘ │
│                              │                  │                       │
│                              ▼                  ▼                       │
│                    ┌────────────────────────────────────┐              │
│                    │ correlator (not yet built)          │              │
│                    │ reads: agentsight.jsonl,             │              │
│                    │        hermes_hooks.jsonl,           │              │
│                    │        probe_scores.jsonl            │              │
│                    │ diffs Hermes's self-report against   │              │
│                    │ kernel truth; flags divergence and    │              │
│                    │ high probe scores; alerts (osascript/ │              │
│                    │ webhook/notification)                 │              │
│                    └────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

## Why Hermes runs inside Docker (not just the model)

This was explicitly revisited mid-project (see conversation log / decision
below) after a proposal to sandbox only the model and let Hermes run
natively. The reasoning that settled it:

Three distinct layers can disagree with each other, and only one of them
requires Hermes's own process to live on a Linux kernel:

1. **Model intent** (what the LLM says it wants to do) — readable via
   activation probes, works regardless of where Hermes's process lives,
   since it only needs access to the model server's internals.
2. **Hermes's own execution/self-report** (`pre_tool_call` logs, Tirith
   verdicts) — application-layer, runs wherever Hermes runs.
3. **Kernel-level ground truth** (what actually executed, what files
   were actually touched, what connections actually opened) — this is
   what AgentSight/eBPF sees, and **eBPF is Linux-kernel-only**. It
   cannot observe a process running on macOS's Darwin/XNU kernel at all,
   full stop, independent of any container-hardening question.

These three layers are NOT redundant. Concrete, real example from this
project's own research: hermes-agent issue #41045 — a `pre_tool_call`
hook returned a block verdict, but due to a bug the block was silently
discarded and the tool call executed anyway. Anything watching only
layers 1 or 2 would have seen "action blocked" and been wrong; only
layer 3 (kernel-level tracing) would have caught that the command
actually ran. This is precisely the failure mode AgentSight exists to
catch, and it can only catch it if Hermes's actual process — the thing
doing the `execve()` calls — lives somewhere eBPF can trace it.

On this Mac, the only Linux kernel available at all is the one inside
Docker Desktop's LinuxKit VM (confirmed real via R1's BTF/eBPF testing).
So: **for AgentSight to watch Hermes's real actions, Hermes's process
must run inside a container in that VM** — not for the sake of
container hardening/cap-drop (Hermes already gets that from its own
documented defaults), but specifically to place its process tree on a
kernel eBPF can observe.

DECISION (2026-09-24, revisited): Hermes runs inside Docker. The model
server (vllm-metal) still runs natively outside Docker (see R7) —
Metal/MLX GPU acceleration is unavailable to a containerized process on
macOS regardless, so there's no benefit to containerizing the model
server here, only Hermes needs to be inside the kernel boundary AgentSight
can see.


## Why hidden-states extraction is async, not inline

`vllm`'s `extract_hidden_states` speculative-decoding path writes hidden
states to disk/shared-memory per completion; folding that into the
synchronous request path would add real latency to every single agent turn.
Given the "observe only" decision, the probe-sidecar reads the
`hidden_states_path` output *after* the completion returns to Hermes, not
before. This means: **the probe score for a turn is available strictly
after the agent has already acted on that turn.** This is a deliberate
tradeoff for phase 1 — it cannot block anything by construction. Moving to
blocking mode (probe-gates-response) requires either (a) accepting the
latency of scoring before Hermes ever sees the completion, or (b) some
form of speculative/provisional response holding, neither of which is
scoped here.

## Model-family constraint

Apollo's published probe weights (`example_results/` in
`ApolloResearch/deception-detection`) were trained against specific Llama
checkpoints (notably Llama-70B-3.3 for the insider-trading dataset). Using
their pretrained probes as-is requires serving that same model family.
Using a different open-weight model (Qwen, Gemma, etc.) means either:
- retraining probes against that model's activations using Apollo's
  training pipeline (`deception_detection/scripts/experiment.py`), or
- treating the probe as untested/exploratory for that model family.

This repo does not pick a model yet. See `docs/RISKS.md` for the open
decision and the hardware tradeoff it implies (70B-class needs real GPU
budget; smaller open-weight models are untested against these probes).

## What is NOT yet real

- AgentSight has not been run against Docker Desktop's LinuxKit VM — the
  BTF/eBPF availability question from earlier research is unresolved
  (`docker/for-mac#6800` is an open, unresolved upstream issue).
- No model has been selected or downloaded.
- `probe_sidecar/` in this repo is a skeleton with the scoring logic
  stubbed, not implemented — it needs Apollo's actual probe-loading code
  vendored or imported as a dependency.
- The `correlator` component (self-report vs kernel-truth diffing) is
  design-only, not started.
- Nothing has been tested end to end. Do not describe this project as
  "working" until each component has a logged, reproducible run recorded
  in `docs/VERIFICATION.md`.
