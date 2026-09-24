# Hermes Secure Sandbox

A self-contained execution environment for a Hermes agent combining three
independent observability layers:

1. **AgentSight** (eBPF) — kernel-level, model-agnostic boundary observation
2. **Hermes native hooks** (`pre_tool_call`/`post_tool_call` + Tirith) — fast,
   in-process, convenience layer
3. **Activation probes** (Apollo Research linear probes on residual-stream
   activations) — only possible because the model is open-weight and served
   locally by vLLM inside this sandbox

**Current phase: observe-only.** Nothing in this repo blocks a tool call.
The goal right now is to get real, logged evidence that each signal means
something, before ever wiring anything to block.

## Status: design + scaffolding, unverified

Read `docs/ARCHITECTURE.md` first, then `docs/RISKS.md` for every open
question and unverified assumption. `docs/VERIFICATION.md` is where real
run results get logged — it's empty right now, which means nothing here
has actually been executed yet. Don't trust anything in `compose/` to
work as-is.

## Layout

```
docs/
  ARCHITECTURE.md   — the design, what's real vs. aspirational
  RISKS.md          — every unverified claim, tracked until resolved
  VERIFICATION.md   — ground-truth log of actual runs (empty so far)
compose/
  docker-compose.yml — skeleton, untested
plugins/
  observability_bridge/ — Hermes plugin, observe-only pre/post_tool_call
                           logger (untested against a live Hermes instance)
probe_sidecar/
  README.md — what needs to be built, not yet implemented
```

## Why this exists

See conversation history / project notes for the full reasoning chain.
Short version: CoT monitoring is known-unreliable (chain-of-thought can be
unfaithful to actual computation); reading model activations directly is a
stronger signal with real empirical backing (Anthropic's sleeper-agent
probes, Apollo's deception probes) but only works for open-weight models
you can actually serve yourself — hence the sandbox needs to both contain
the agent AND host the model.
