# Open Risks / Unverified Claims

This file tracks every assumption in ARCHITECTURE.md that has NOT been
empirically confirmed. Move an item to VERIFICATION.md (with real command
output / logs) once tested; do not delete it from here until then.

## R1: AgentSight eBPF viability on Docker Desktop (macOS host) — RESOLVED 2026-09-24

- See `docs/VERIFICATION.md` 2026-09-24 entries (prerequisites check, then
  live probe attach) for real command output.
- CONFIRMED, prerequisites: Docker Desktop 4.92.0 (LinuxKit kernel 7.0.12)
  exposes `/sys/kernel/btf/vmlinux` (6.7MB, non-empty) and a mountable,
  populated `/sys/kernel/debug` inside a privileged container. The
  specific concern raised by the open `docker/for-mac#6800` issue (BTF not
  exposed) does NOT reproduce on this Docker Desktop version.
- CONFIRMED, live attach: a real bpftrace eBPF program was compiled,
  loaded, verified, attached, and executed successfully
  (`quay.io/iovisor/bpftrace:latest`, "Attaching 1 probe..." +
  correct program output). Ran via amd64-on-arm64 emulation (Docker
  printed an explicit platform-mismatch warning) — worked anyway, but an
  arm64-native image should be preferred once available.
- R1 is now considered resolved for the core feasibility question: eBPF
  tooling (and by extension AgentSight, which depends on the same
  kernel capabilities) is viable on Docker Desktop on this Mac, no
  separate Linux VM required.
- Remaining, now ordinary (non-blocking) follow-up work: test AgentSight's
  actual binary (not just bpftrace as a proxy), trace a real target
  process instead of a trivial BEGIN-block program, prefer arm64-native
  images once available.
- Process note: the live-attach command could not be run through Hermes's
  own terminal tool in the desktop app — it repeatedly hit an
  approval-dialog timeout neither the user nor the agent could see or
  resolve. User ran it directly in a regular terminal instead. Worth
  investigating as a possible desktop-app approval-flow gap before
  relying on Hermes's terminal tool for privileged/pull-heavy commands
  elsewhere in this project.

## R0: Container runtime choice — Docker Desktop vs. fully-OSS alternatives

- Docker Desktop's Engine/CLI/containerd are open source, but the Desktop
  app itself is proprietary and nudges account creation. Fully-OSS,
  no-account alternatives exist and were evaluated:
  - **Colima** (MIT) — macOS/Linux only, CLI-only, Docker-compatible,
    built on Lima/QEMU.
  - **Podman** (Apache 2.0) — macOS/Windows/Linux, **daemonless**
    (no privileged background service), arguably a better architectural
    fit for a project whose whole premise is "don't trust the thing
    you're sandboxing to police itself" — no persistent privileged daemon
    is one less thing to compromise.
  - **Rancher Desktop** (Apache 2.0) — macOS/Windows/Linux, GUI, ships k3s.
- Decision (2026-09-24): stay on Docker Desktop for now since R1 already
  produced a verified positive result on it (BTF+debugfs confirmed, see
  VERIFICATION.md). Re-deriving R1 against a different runtime's QEMU-based
  VM is deferred, not abandoned — Colima/Lima/Podman/Rancher Desktop's VMs
  are UNVERIFIED for the same BTF/debugfs prerequisites. Revisit this once
  the core pipeline (R1 live probe attach, R2-R7) is proven end-to-end on
  Docker Desktop; swapping the container runtime later should be a mostly
  mechanical change (same docker-compose.yml, different VM underneath) as
  long as the replacement's VM exposes the same eBPF prerequisites.

## R2: Hermes `docker` terminal backend — multi-container support — RESOLVED 2026-09-24

- Confirmed via `hermes-agent.nousresearch.com/docs/user-guide/configuration`:
  Hermes's `docker` backend manages exactly **one persistent container**
  per session (`container_persistent: true` = shared container across
  sessions, no native compose/multi-container orchestration inside Hermes
  itself).
- However, `terminal.docker_extra_args` passes arbitrary flags straight
  through to the underlying `docker run` — including `--network=<name>`.
  This means Hermes's single managed container CAN join an externally
  launched docker-compose network as a sibling service, without Hermes
  needing any multi-container awareness.
- CONFIRMED empirically (not just from docs): created a test bridge
  network (`docker network create`), ran a stand-in "vllm-serve" container
  on it, then a second container joining the same network resolved and
  pinged the first purely by container name (Docker's embedded DNS across
  a user-defined bridge network). Real output:
  ```
  PING test-vllm-stub (172.18.0.2): 56 data bytes
  64 bytes from 172.18.0.2: seq=0 ttl=64 time=0.083 ms
  ```
  This is the exact mechanism our compose stack needs: Hermes's agent
  container reaching `vllm-serve:8000` by name.
- Practical design implication: our `compose/docker-compose.yml` should
  define the shared network (already does, `sandbox-net`), launch
  agentsight/vllm-serve/probe-sidecar via `docker compose up` as usual,
  and instead of also defining `hermes-agent` as a compose service, launch
  Hermes itself via its own CLI/config with:
  ```yaml
  terminal:
    backend: docker
    docker_extra_args:
      - "--network=sandbox-net"
  ```
  so Hermes's own container-lifecycle management (persistence, reaping,
  etc.) stays intact, while still landing on the shared compose network.
  This is simpler and more robust than fighting Hermes to adopt compose
  natively. `compose/docker-compose.yml` needs updating to drop the
  `hermes-agent` service block and replace it with this note (tracked as
  a follow-up edit, not yet applied as of this entry).
- Not tested: `docker_volumes` + shared log volume interaction (whether
  Hermes's container can write to the same `sandbox-logs` volume the
  other services read from) — small, low-risk gap, easy to verify same
  way as above whenever the pieces are assembled for a real run.

## R3: `pre_tool_call` hook reliability — RESOLVED (minimal case) 2026-09-24

- See `docs/VERIFICATION.md` 2026-09-24 entry for real command output.
- CONFIRMED on installed Hermes Agent v0.21.0 (2026.8.31): both
  `pre_tool_call` and `post_tool_call` fire reliably, correctly ordered,
  correctly attributed to the real tool name, for an actual tool call in
  a real `hermes chat -q` session. Verified with a purpose-built
  diagnostic plugin + `hermes plugins doctor --ci` + a real trace log,
  not inferred from version numbers alone.
- Important layout correction discovered during this test: native plugins
  need `plugin.yaml` + `__init__.py` (not an arbitrarily-named `.py`
  file) in a flat directory under `~/.hermes/profiles/<profile>/plugins/`.
  An earlier attempt using `plugin.py` silently failed to be discovered.
  This is the correct pattern for the project's real
  `plugins/observability_bridge` — needs the same fix applied (currently
  named `plugin.py`, see follow-up task).
- Residual, NOT tested: open reports of unreliable firing in other
  execution contexts (hermes-agent#25204 kanban-worker, #44582) — this
  test used the simplest possible context (one-shot `chat -q`). Not
  chased further since this project's actual usage pattern doesn't match
  those reported contexts, but worth re-checking if the observability
  plugin is ever deployed inside a gateway/kanban-worker context.
- NOT tested: whether returning `{"action": "block", ...}` actually
  blocks (the #41045 regression scenario) — irrelevant to our observe-only
  design, so deliberately not chased.

## R4: `vllm` `extract_hidden_states` overhead and API stability — CORE BLOCKER RESOLVED 2026-09-24, narrower question remains

- RESOLVED: "does local model serving work at all on this hardware" — YES.
  Switched from CPU-in-Docker (proven non-viable, 3/3 identical stalls,
  amd64-emulation root cause) to `vllm-metal` (MLX + Metal, native arm64,
  outside Docker). Installed via the project's own `install.sh`, verified
  `current_platform` prints `MetalPlatform` (not `CpuPlatform`), served
  `Qwen/Qwen3-0.6B`, got a real `200 OK` completion with correct content
  ("Paris"). Full detail in `docs/VERIFICATION.md` 2026-09-24 "RESOLVED —
  vllm-metal native install" entry. This is a genuine, controlled A/B
  result: identical task, Docker-emulated = stalled 3/3, native
  arm64/Metal = worked immediately.
- REMAINING OPEN QUESTION (narrower than before): does `extract_hidden_states`
  / the KV Connector hidden-states-extraction mechanism (the actual R4/R6
  scope — this is what the probe-sidecar needs) work under vllm-metal's
  MLX/Metal backend specifically? That plumbing was documented and built
  against mainline CUDA vLLM; vllm-metal is a separate platform plugin and
  may not implement the same KV Connector internals. NOT YET TESTED.
- Original latency/overhead question (extract_hidden_states cost per
  completion in an agent loop) also still unverified — was never reached,
  now unblocked to actually test.
- Paged attention (vllm-metal's default KV cache path) is still labeled
  "experimental" by upstream docs — worth keeping in mind.

## R5: Apollo probe transfer to a different model / different vLLM version

- Published probe weights are tied to specific model checkpoints (Llama
  family). No claim here that they'd produce meaningful scores against any
  other model without retraining. Treat probe scores as **exploratory
  only** until validated: e.g. deliberately construct a known-deceptive
  transcript and a known-honest transcript on the actual served model, and
  confirm the probe separates them before trusting any score from real
  agent traffic.

## R6: NNsight vs. raw vLLM hidden-states extraction — which to build against

- Two viable paths to get activations out of a serving vLLM instance:
  (a) vLLM's native `extract_hidden_states` speculative-decoding path
  (b) NNsight's vLLM integration (sync/async activation read+write hooks)
- Not yet decided which is the better fit. NNsight is purpose-built for
  interpretability (closer semantics to what Apollo's probe code expects)
  but is a newer, smaller-community dependency than vLLM's own native
  feature. Needs a short spike comparing both against a trivial "extract
  layer N residual stream for one completion" test before committing.

## R7: Hardware / model size — RESOLVED, REVISED 2026-09-24

- Host: Apple M5, 32GB RAM (confirmed via `sysctl`).
- ORIGINAL DECISION (superseded): CPU-only inference inside Docker,
  correctness-first. PROVEN NON-VIABLE via R4's 3/3 identical stalls,
  root-caused to amd64-on-arm64 Docker emulation breaking vLLM's
  worker-process spawn/IPC.
- REVISED, CONFIRMED DECISION: `vllm-metal` (MLX + hand-written Metal
  kernels), installed and run NATIVELY on the Mac host, OUTSIDE Docker.
  Real evidence: `current_platform` → `MetalPlatform` (GPU-backed, not
  CPU fallback), served `Qwen/Qwen3-0.6B`, got a real 200 OK completion.
  See `docs/VERIFICATION.md` 2026-09-24 "RESOLVED — vllm-metal" entry.
- Hard constraints for this path (from a source specifically covering
  this exact hardware — "Running and Profiling vLLM on M5 MacBook Pro"):
  Python 3.12 exactly (3.13/3.14 unsupported — wheel is `cp312`-specific),
  native arm64 Python required (plugin explicitly refuses Rosetta), `uv`
  for install/dependency management, ~10-20 min compile time for vLLM
  core from source on first install.
- ARCHITECTURAL CONSEQUENCE (not yet resolved, tracked under R2/R4): this
  breaks the "everything containerized" property R2 established. The
  model server is a native host process, not a compose service — Hermes
  (Docker container) needs to reach it via `host.docker.internal:8000`
  or equivalent, not compose-network DNS. AgentSight continues to watch
  the Hermes container as before, but the model server itself sits
  outside that Docker/kernel-observability boundary. This tradeoff needs
  explicit design treatment, not silent adoption — see compose file
  update.
- Specific model used for this smoke test: `Qwen/Qwen3-0.6B` (not the
  Llama family Apollo's probes were trained on — R5's model-transfer
  concern is unaffected by this change, still open).
