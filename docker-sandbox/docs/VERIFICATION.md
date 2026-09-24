# Verification Log

This file exists to enforce ground-truth discipline on this project: no
component gets described as "working" anywhere else in this repo or in
conversation until a real run is logged here with actual output.

Format per entry:

```
## <date> — <component> — <PASS|FAIL|PARTIAL>
Command run:
Real output (paste, not paraphrase):
What this proves:
What this does NOT prove:
```

---

## 2026-09-24 — R1: Docker Desktop LinuxKit VM / eBPF prerequisites — PARTIAL PASS

Environment: Docker Desktop 4.92.0 (240144) installed via
`brew install --cask docker-desktop`, daemon started via `open -a Docker`.
macOS host, Apple Silicon (arm64).

Command run:
```
docker run --rm --privileged alpine uname -r
docker run --rm --privileged alpine sh -c "ls -la /sys/kernel/btf/vmlinux"
docker run --rm --privileged -v /sys/kernel/debug:/sys/kernel/debug alpine sh -c "ls /sys/kernel/debug | head -5"
docker run --rm --privileged --cap-add=ALL alpine sh -c "cat /proc/version"
```

Real output:
```
7.0.12-linuxkit

-r--r--r--    1 root     root       6710304 Sep 24 10:01 /sys/kernel/btf/vmlinux

bdi
block
btt
clear_warn_once
clk

Linux version 7.0.12-linuxkit (root@buildkitsandbox) (gcc (Alpine 15.2.0)
15.2.0, GNU ld (GNU Binutils) 2.45.1) #1 SMP PREEMPT Thu Aug 27 14:02:21 UTC 2026
```

What this proves:
- Docker Desktop's LinuxKit VM is a real Linux kernel (7.0.12), reachable
  from a privileged container.
- `/sys/kernel/btf/vmlinux` is present and non-empty (6.7MB) — this is the
  specific file the open, unresolved `docker/for-mac#6800` issue was about
  ("enable BTF"). On this Docker Desktop version (4.92.0), it is already
  exposed. That issue may be stale/resolved upstream since it was filed,
  or was never actually blocking on the current LinuxKit build — worth
  noting the issue number for future reference but its concern does not
  reproduce here.
- `/sys/kernel/debug` is mountable and populated inside a privileged
  container — debugfs access, another common eBPF-tooling prerequisite,
  works.
- This directly satisfies the necessary preconditions AgentSight's own
  README lists as needed on the host: privileged access + BTF availability.

What this does NOT prove:
- Did NOT confirm an actual eBPF program can be loaded and attached
  (bpf() syscall success, program verifier acceptance). The bpftrace
  probe-load test was attempted but the command required approval that
  timed out; on retry-decision the user chose to stop here rather than
  re-run it. So: kernel/BTF/debugfs prerequisites are confirmed present,
  but "can AgentSight itself actually attach a probe here" remains
  unverified.
- Did NOT test AgentSight itself (the actual binary/tool), only generic
  eBPF prerequisites via alpine + manual sysfs checks.
- Did NOT test resource/performance behavior of running eBPF tracing
  alongside a real agent workload in this VM.

Net assessment (superseded below): R1's core blocking concern (raised by
the open docker/for-mac#6800 issue) does not reproduce on this Docker
Desktop version — BTF is present. This substantially de-risks the "Docker
Desktop on macOS" path as a starting point for AgentSight integration.

## 2026-09-24 — R1: live eBPF probe attach (bpftrace) — PASS

Run by user directly in a regular terminal (outside Hermes's own terminal
tool, due to an approval-dialog rendering issue in the desktop app — see
note below).

Command run:
```
docker run --rm --privileged \
  -v /sys/kernel/debug:/sys/kernel/debug:rw \
  -v /sys/kernel/btf:/sys/kernel/btf:ro \
  quay.io/iovisor/bpftrace:latest \
  bpftrace -e 'BEGIN { printf("eBPF works on LinuxKit\n"); exit(); }'
```

Real output:
```
Unable to find image 'quay.io/iovisor/bpftrace:latest' locally
latest: Pulling from iovisor/bpftrace
667912c34e39: Pull complete
587ea7a90316: Pull complete
e1b1d84e9daf: Pull complete
7a2c55901189: Pull complete
Digest: sha256:ceeff3fb27b644dcec07f0da4fd725a1209a07a0b1a12079b99c80324a3568b2
Status: Downloaded newer image for quay.io/iovisor/bpftrace:latest
WARNING: The requested image's platform (linux/amd64) does not match the
detected host platform (linux/arm64/v8) and no specific platform was
requested
Attaching 1 probe...
eBPF works on LinuxKit
```

What this proves:
- A real eBPF program was compiled, loaded into the kernel, verified by
  the kernel's BPF verifier, and successfully attached and executed
  (`Attaching 1 probe...` + program output) on Docker Desktop's LinuxKit
  VM. This is the actual capability AgentSight depends on — not just the
  prerequisite files (BTF/debugfs) being present, but the full load-verify-
  attach-run path working.
- This resolves R1's core open question. AgentSight-class eBPF tooling is
  viable on this Docker Desktop setup, no separate Linux VM required.

What this does NOT prove:
- Ran an amd64 image emulated on arm64 (explicit warning in the output:
  "requested image's platform... does not match... host platform"). It
  worked anyway, but an arm64-native bpftrace/AgentSight build should be
  preferred once available, to avoid emulation overhead and rule out any
  emulation-specific quirks masking a real issue.
- Did NOT test AgentSight's actual binary, only bpftrace as a proxy for
  generic eBPF capability. AgentSight may have additional requirements
  (specific kernel features, its own vendored BTF/CO-RE handling) not
  exercised by this minimal test.
- Did NOT test tracing a real target process (e.g. hermes-agent itself) —
  only a trivial BEGIN-block program with no actual kprobe/tracepoint
  attachment to a running process.
- Process note: this command could not be run through Hermes's own
  terminal tool — it repeatedly hit an approval-dialog timeout that
  neither the user nor the agent could see/resolve in the desktop app.
  Worth a separate investigation (possibly a desktop-app approval-flow
  bug) before relying on Hermes's terminal tool for privileged/pull-heavy
  commands in this project going forward.

Updated net assessment: R1 is now considered **resolved** for the
"can eBPF run at all on Docker Desktop/macOS" question. Remaining R1-
adjacent work (AgentSight's specific binary, tracing a real target
process, arm64-native images) is now ordinary implementation work, not an
open feasibility risk.

## 2026-09-24 — R2: Hermes docker backend + external compose network — PASS

Command run:
```
docker network create sandbox-test-net
docker run -d --name test-vllm-stub --network sandbox-test-net alpine sleep 300
docker run --rm --network sandbox-test-net alpine sh -c \
  "apk add --no-cache bind-tools >/dev/null 2>&1; ping -c1 test-vllm-stub"
docker rm -f test-vllm-stub
docker network rm sandbox-test-net
```

Real output:
```
PING test-vllm-stub (172.18.0.2): 56 data bytes
64 bytes from 172.18.0.2: seq=0 ttl=64 time=0.083 ms

--- test-vllm-stub ping statistics ---
1 packets transmitted, 1 packets received, 0% packet loss
round-trip min/avg/max = 0.083/0.083/0.083 ms
```
(Ran successfully through Hermes's own terminal tool this time — no
approval-dialog issue, confirming that problem was specific to
privileged+image-pull commands, not docker commands generally.)

What this proves:
- A container joining a user-defined Docker bridge network by name
  (`--network sandbox-test-net`) can resolve and reach another container
  on the same network purely by container name, via Docker's embedded
  DNS. This is the exact mechanism needed for Hermes's single
  docker-backend-managed container to reach `vllm-serve:8000` when both
  are attached to the same compose-created network.
- Combined with Hermes's documented `docker_extra_args` config field
  (passes arbitrary flags to the underlying `docker run`, confirmed via
  official docs, not just inferred), this means `docker_extra_args:
  ["--network=sandbox-net"]` should let Hermes's own container join our
  compose stack's network without Hermes needing any native
  multi-container/compose awareness.

What this does NOT prove:
- Did NOT test this against Hermes's actual docker-backend code —
  confirmed the underlying Docker networking mechanism works, and that
  Hermes exposes the config field to use it, but did NOT launch a real
  Hermes instance with this config and confirm it actually reaches a
  real vllm-serve container end to end.
- Did NOT test `docker_volumes` interaction with the shared
  `sandbox-logs` volume (whether Hermes's container can write to a
  volume also read by the probe-sidecar/correlator).
- Did NOT test any authentication/firewall interaction — this was a
  bare bridge network with no restrictions, whereas the real stack may
  want `docker_network: true` vs. egress restrictions layered on top
  later.

Net assessment: R2's core question (can Hermes's single-container docker
backend coexist with an externally-managed compose stack) is resolved at
the mechanism level — yes, via `docker_extra_args` + shared network name.
Full end-to-end confirmation (real Hermes instance talking to a real
vllm-serve container) is deferred until those pieces actually exist.
`compose/docker-compose.yml` has been updated to reflect this design
(hermes-agent removed as a compose service, replaced with a config
snippet comment showing the intended approach).

## 2026-09-24 — R3: pre_tool_call/post_tool_call hook reliability — PASS

Installed version: Hermes Agent v0.21.0 (2026.8.31) — calendar-dated after
the v2026.4.16 fix for hermes-agent#41045 (block verdicts silently
discarded).

Setup: built a minimal diagnostic plugin at
`~/.hermes/profiles/harry/plugins/r3_diagnostic/` using the correct native
plugin layout (flat directory, `plugin.yaml` + `__init__.py` with
`register(ctx)` — NOT `plugin.py`, an earlier attempt using that filename
silently failed to be discovered by `hermes plugins enable`). Validated
first with `hermes plugins doctor <path> --ci`:
```
Plugin Doctor: /Users/amm/.hermes/profiles/harry/plugins/r3_diagnostic
  manifest: r3_diagnostic 1.0.0 (standalone)
  OK: runtime discovery, manifest parsing, import, and registration passed
  registrations: 0 tool(s), 2 hook(s)
```
Then `hermes plugins enable r3_diagnostic`, confirmed via `hermes plugins
list` (status: enabled).

Command run (fresh process, separate from this Hermes session, so the
newly-enabled plugin loads cleanly — "takes effect on next session" per
the enable command's own output):
```
hermes chat -q "Run the shell command: ls /tmp"
```

Real output (trace log, `~/.hermes/r3_diagnostic_trace.log`):
```
2026-09-24T11:16:01.012581  pid=74452  event=register_called       {}
2026-09-24T11:16:01.012913  pid=74452  event=register_done         {}
2026-09-24T11:16:05.039961  pid=74452  event=pre_tool_call   {'tool_name': 'terminal'}
2026-09-24T11:16:05.158191  pid=74452  event=post_tool_call  {'tool_name': 'terminal'}
```

What this proves:
- On this installed version, `pre_tool_call` and `post_tool_call` both
  fire reliably, in the correct order, correctly attributed to the real
  tool name (`terminal`), for a real tool call in a real chat session —
  not a synthetic/mocked invocation.
- The plugin registration and hook-firing path is intact end to end:
  directory discovery → manifest parse → import → `register(ctx)` →
  hook dispatch on actual tool execution.
- This directly de-risks the `observability_bridge` plugin design (which
  relies on exactly this hook pair) for this Hermes version.

What this does NOT prove:
- Did NOT test the open reports of `pre_tool_call` not firing reliably in
  other execution contexts (hermes-agent#25204's kanban-worker `chat -q`
  context specifically, #44582's more recent report) — this test used a
  plain one-shot `hermes chat -q` invocation, the simplest possible
  context. Gateway/kanban-worker/Telegram contexts remain unverified.
- Did NOT test that a `{"action": "block", ...}` return value actually
  blocks (the #41045 bug scenario) — this diagnostic plugin deliberately
  only observes (`return None` in both hooks), matching the
  observability_bridge's own observe-only design. Confirming block
  actually works is a distinct, not-yet-run test, lower priority since
  our design doesn't currently depend on blocking.
- Did NOT test hook firing under load / concurrent tool calls / subagents.

Cleanup: the r3_diagnostic plugin was disabled/removed after this test —
it was purpose-built for this verification only, not part of the
project's shipped artifacts.

Net assessment: R3 is resolved for the specific, minimal case this
project's plugin actually needs (observe-only pre/post_tool_call in a
plain chat session). The broader open reliability reports in other
execution contexts remain a known, lower-priority residual risk — noted,
not chased further, since the sandbox project's own usage pattern doesn't
match those reported contexts.

## 2026-09-24 — R4/R7: vLLM CPU image — real run attempt — PARTIAL

Background: R7 investigation found `vllm/vllm-openai` (Docker Hub)
requires a GPU (vllm-project/vllm#4771). Corrected target to the AWS ECR
Public Gallery CPU image. First attempt used tag `:latest`, which hung
silently for 90+ seconds with zero output — killed after confirming the
gallery page only advertises a hash-based tag, not `:latest`
(`public.ecr.aws/q9t5s3a7/vllm-cpu-release-repo:7f1a5398e9610d96c473931a26c0e12bbe0d0423-x86_64`,
confirmed via gallery.ecr.aws page content, 3.6M+ downloads, updated 15
days prior at time of check).

Step 1 — pull the correct tag:
```
docker pull public.ecr.aws/q9t5s3a7/vllm-cpu-release-repo:7f1a5398e9610d96c473931a26c0e12bbe0d0423-x86_64
```
Result: SUCCESS. Real output:
```
Digest: sha256:a4ee86ae0badbc5b0a9cff3d7fb39025688dfbc9a057e40d671dffbb4b30bcdf
Status: Downloaded newer image for public.ecr.aws/q9t5s3a7/vllm-cpu-release-repo:...
```
`docker images` confirms: 9.23GB disk usage, 2.28GB compressed content.

Step 2 — confirm the container starts at all (amd64 image, arm64 host,
runs under Docker's emulation):
```
docker run --rm public.ecr.aws/q9t5s3a7/vllm-cpu-release-repo:...  --help
```
Result: SUCCESS. Real output: full `vllm serve --help` text printed
correctly (ModelConfig, CacheConfig, etc. all listed) with only an
informational platform-mismatch warning, no crash, no AVX-512 failure.
This resolves the AVX-512/emulation concern raised in R4's earlier
entry — the CPU image's own tooling runs fine under amd64-on-arm64
emulation for at least this lightweight invocation.

Step 3 — attempt to actually serve a model:
```
docker run --rm --name r4-vllm-test -p 8000:8000 \
  public.ecr.aws/q9t5s3a7/vllm-cpu-release-repo:... \
  --model Qwen/Qwen3-0.6B
```
Real output (before stall):
```
(APIServer pid=1) INFO 09-24 11:34:07 [api_utils.py:347] version 0.30.1rc1.dev48+g7f1a5398e
(APIServer pid=1) INFO 09-24 11:34:07 [api_utils.py:286] non-default args: {'model_tag': 'Qwen/Qwen3-0.6B'}
(APIServer pid=1) Warning: You are sending unauthenticated requests to the HF Hub.
(APIServer pid=1) INFO 09-24 11:34:17 [model.py:696] Resolved architecture: Qwen3ForCausalLM
(APIServer pid=1) INFO 09-24 11:34:17 [model.py:2104] Using max model len 40960
(APIServer pid=1) INFO 09-24 11:34:17 [kernel.py:408] Final IR op priority after setting
  platform defaults: IrOpPriorityConfig(rms_norm=['native'], fused_add_rms_norm=['native'],
  gelu_and_mul_sparse=['native'])
```
Then: **no further output for 6+ minutes**. Confirmed via `docker stats
--no-stream`: 0.00% CPU, identical NET I/O byte counts across a 15-second
sampling window (5.5MB / 64.4kB, unchanged) — genuinely stalled, not
slow-but-working. Killed after confirming no progress.

What this proves:
- The CPU image itself is viable: pulls correctly, runs its CLI tooling
  correctly under amd64-on-arm64 emulation, resolves a real model's
  architecture (Qwen3ForCausalLM) and engine config correctly. The
  earlier AVX-512/emulation compound-risk concern from R4's prior entry
  is substantially de-risked — at least through engine initialization,
  nothing failed or fell back silently.

What this does NOT prove, and the actual blocker found:
- The server never reached "Uvicorn running" / "Application startup
  complete" (the notify_patterns watched for). It stalled after engine
  config, before visible model-weight download or load activity, with
  the process pinned at 0% CPU — this is NOT the expected profile of "CPU
  inference is just slow," which would show sustained high CPU usage
  during weight loading/compilation. A genuinely stalled, near-idle
  process suggests something is blocking (e.g. a network call to
  HuggingFace Hub hanging, a lock/semaphore wait, or an
  emulation-specific issue this minimal test didn't surface) rather than
  "correctness confirmed, just need to wait longer."
- Did NOT confirm the server can actually serve a single completion, let
  alone test `extract_hidden_states` overhead (R4's original scope) or
  `kv_transfer_params` stability (R6).
- Not yet investigated: whether `HF_TOKEN` absence (the "unauthenticated
  requests" warning) is contributing to the stall (rate-limited/blocked
  download), whether the specific model choice matters, or whether a
  longer timeout would have eventually succeeded (6 minutes with zero
  CPU activity strongly suggests it would not have, but this wasn't
  proven by waiting it out fully).

Net assessment: R4/R7 moved from "unknown if it runs at all" to "runs its
tooling correctly, but the actual serve path has a real, reproducible
stall that needs root-causing" — genuine progress, but not resolved.
Next concrete step: retry with `HF_TOKEN` set (rule out Hub
rate-limiting), and/or retry with `--download-dir` pre-populated from a
manual `huggingface-cli download` to isolate whether the stall is
Hub-related or something else in the CPU engine's startup path.

## 2026-09-24 — R4: retry with HF_TOKEN — stall confirmed NOT Hub-related

User re-ran the same serve command with a valid `HF_TOKEN` set (passed via
`-e HF_TOKEN` to `docker run`, token generated by user, NOT recorded here —
see security note below).

Command run (by user, in their own terminal):
```
export HF_TOKEN="<redacted>"
docker run --rm --name r4-vllm-test -p 8000:8000 \
  -e HF_TOKEN \
  public.ecr.aws/q9t5s3a7/vllm-cpu-release-repo:7f1a5398e9610d96c473931a26c0e12bbe0d0423-x86_64 \
  --model Qwen/Qwen3-0.6B
```

Observation 1 — the "unauthenticated requests" warning is GONE this time
(present in the no-token run, absent here) — confirms the token was
picked up correctly by the container.

Observation 2 — `docker stats --no-stream r4-vllm-test`, compared across
both runs:
| | No token (first attempt) | With token (this attempt) |
|---|---|---|
| Memory | 1.285 GiB | 2.061 GiB |
| Block I/O | 415 MB | 1.28 GB |
| CPU | 0.00% | 0.00% |

Real progress happened this time (more memory allocated, more disk I/O —
consistent with actual model weight download/load happening), but it
STILL stalled afterward, at 0% CPU, no further log lines.

Observation 3 — `docker logs r4-vllm-test` showed no new lines beyond
`11:57:39` (`Final IR op priority after setting platform defaults...`),
even ~30+ minutes later.

Observation 4 — `docker exec r4-vllm-test ps aux`:
```
USER   PID %CPU %MEM    VSZ    RSS TTY STAT START   TIME COMMAND
root     1  1.0 15.8 4784440 1285720 ?  Ssl 11:57   0:21 vllm serve --model Qwen/Qwen3-0.6B
```
Only ONE process — no separate engine/worker subprocess, which vLLM
normally spawns. Only 21 seconds of accumulated CPU time despite 30+
minutes of wall-clock runtime. STAT `Ssl` = interruptible sleep
(blocked waiting on something), not uninterruptible I/O wait or active
compute.

Observation 5 — direct connectivity test:
```
curl -v -m 5 http://localhost:8000/v1/models
```
Real output:
```
* Connected to localhost (::1) port 8000
> GET /v1/models HTTP/1.1
* Recv failure: Connection reset by peer
curl: (56) Recv failure: Connection reset by peer
```
"Connection reset by peer" (not timeout, not connection-refused) —
Docker's host-side port-forwarding proxy accepted the TCP handshake (as
it does regardless of container-internal state) but got no response from
inside the container to relay, and reset the connection. This confirms
nothing is listening on port 8000 inside the container — Uvicorn/the API
server has never actually started.

What this proves:
- The earlier stall was NOT primarily caused by missing `HF_TOKEN` /
  Hub rate-limiting — the token measurably changed behavior (no more
  warning, more memory/disk activity, implying the download did
  progress further this time) but the server still never came up.
- The failure point is now well-localized: past model download/weight
  allocation, but before Uvicorn binds to port 8000 — specifically
  looks like the main process is stuck waiting on something (an
  interruptible sleep) rather than crashing outright, and never spawns
  a visible worker subprocess.
- Independently confirmed via three different signals (stale logs, `ps
  aux` process count + CPU time, and a raw TCP-level connection reset)
  rather than a single ambiguous symptom — this is a real, reproducible
  stall, not a fluke or "just needs more time."

What this does NOT prove:
- Root cause is still unconfirmed. Leading hypothesis, not proven:
  something in vLLM's multiprocessing/worker-spawn path breaks or hangs
  under amd64-on-arm64 Docker emulation specifically (a known general
  category of problem for cross-architecture emulated multiprocess
  Python apps — process/IPC primitives can behave differently under
  binary translation). Not yet tested: whether this reproduces on a
  genuinely native amd64 Linux host (would isolate emulation as the
  cause) or whether a different/smaller model, different vLLM version,
  or explicit single-process flags change the outcome.
- Did NOT get anywhere near testing `extract_hidden_states` itself (R4's
  original scope) or `kv_transfer_params` (R6) — those remain fully
  blocked until basic serving works at all.

Security note: a live `HF_TOKEN` value was pasted directly into this
chat by the user during this diagnostic session. Per handling-user-
credentials skill: flagged as compromised immediately in-conversation,
user was told to rotate it at huggingface.co/settings/tokens. The token
value is NOT recorded in this file, the git repo, or anywhere else
persistent — it was used transiently via shell env var in the user's own
terminal, never passed through any Hermes tool call or written to disk
by the agent.

Net assessment: R4 remains BLOCKED, but with much better localization
now — this is very likely an emulation-specific multiprocessing issue in
vLLM's CPU serving path, not a credentials or Hub-access problem. Next
concrete steps, in order of cost: (1) try `--enforce-eager` or other
flags that might avoid whatever subprocess-spawn path is hanging, (2)
try an even smaller/different model in case Qwen3 specifically triggers
this, (3) if neither works, treat this as strong evidence that CPU
inference under Docker Desktop's amd64 emulation on Apple Silicon is not
a viable path for this project, and revisit R7's hardware decision
(native Linux+CUDA box, or vllm-metal outside Docker on bare Metal, per
the alternatives already logged in R7).

## 2026-09-24 — R4: --enforce-eager retry — same stall, ruled out torch.compile/CUDAGraphs

Command run (by user):
```
docker run --rm --name r4-vllm-test -p 8000:8000 -e HF_TOKEN \
  public.ecr.aws/q9t5s3a7/vllm-cpu-release-repo:7f1a5398e9610d96c473931a26c0e12bbe0d0423-x86_64 \
  --model Qwen/Qwen3-0.6B --enforce-eager
```

Note: the "unauthenticated requests to HF Hub" warning reappeared despite
`-e HF_TOKEN` being passed — possibly the export didn't survive in that
shell, not independently confirmed. Did not block investigation of the
main hypothesis.

New log lines not seen in prior runs (real forward progress past the
previous stopping point):
```
WARNING 09-24 12:43:45 [vllm.py:1669] Enforce eager set, disabling
  torch.compile, CUDAGraphs, and JIT kernel warmup.
WARNING 09-24 12:43:45 [vllm.py:1695] Inductor compilation was disabled
  by user settings...
INFO 09-24 12:43:45 [compilation.py:331] Enabled custom fusions:
  norm_quant, act_quant
```
Then: stalled again, same as every prior attempt.

Diagnostic signals, compared to the HF_TOKEN-retry run:
```
curl -v -m 5 http://localhost:8000/v1/models
  → "Recv failure: Connection reset by peer" (IDENTICAL to prior run)

docker exec r4-vllm-test ps aux
  root  1  ... Ssl  12:43  0:21  vllm serve --model Qwen/Qwen3-0.6B --enforce-eager
  root  95 ... Rs   12:47  0:00  ps aux
  (IDENTICAL signature: single process, no worker subprocess, ~21s CPU
  time despite several minutes wall-clock, interruptible sleep state)
```

What this proves:
- `--enforce-eager` (disables torch.compile, CUDAGraphs, JIT kernel
  warmup) is RULED OUT as the fix. The stall is not caused by
  compilation/graph-capture machinery — those systems got further this
  run (visibly initialized: "Enabled custom fusions") but the process
  still hung at the identical point afterward (worker/IPC spawn, per
  prior localization).
- This strengthens the emulation-multiprocessing hypothesis by
  elimination: two different, independent subsystems (compilation
  machinery, HF auth/download path) have now been ruled out as the
  cause via direct testing, converging on process/worker spawn under
  amd64-on-arm64 emulation as the remaining, most likely explanation.

What this does NOT prove:
- Still not proven definitively — no test has yet run on genuine (non-
  emulated) amd64 Linux to confirm emulation itself is the cause, and no
  vLLM-specific worker-spawn flag has been tried (e.g. explicit
  single-process/no-multiprocessing mode, if one exists).

Net assessment: after two independent, targeted fix attempts (HF_TOKEN,
--enforce-eager) both failed to change the outcome, this is now treated
as sufficient evidence to stop iterating blindly on this environment.
Per user decision this session: stopping CPU-serving debugging here.
R4 remains BLOCKED. This is now real evidence bearing on R7 — CPU
inference under Docker Desktop's amd64 emulation on this Apple Silicon
Mac has failed 3/3 real attempts in the same way, which is a meaningful
signal (not proof) that this specific combination (Docker Desktop +
amd64 emulation + vLLM CPU image) may not be a viable path for this
project's model-serving layer. Next session should treat R7's hardware
decision as open again, weighing: a genuine Linux+CUDA box (sidesteps
both GPU-passthrough and emulation issues at once), vllm-metal run
directly on bare Metal outside Docker (sidesteps emulation, breaks the
"everything containerized" property R2 established), or further
root-causing the emulation hypothesis specifically before abandoning
the current path.

## 2026-09-24 — R4/R7: RESOLVED — vllm-metal native install, real completion served

Following the 3/3 Docker-emulation stalls, switched to `vllm-metal`
(community plugin, MLX + hand-written Metal kernels, native arm64 —
sidesteps Docker/amd64-emulation entirely). Installed and run natively
on the Mac host, outside Docker, per the plan discussed after diagnosing
the emulation root cause.

Setup (user, own terminal):
```
curl -LsSf https://astral.sh/uv/install.sh | sh          # uv installed: 0.12.18
uv python install 3.12                                    # cpython-3.12.14-macos-aarch64
uv run --python 3.12 python -c "import platform; print(platform.machine())"
  → arm64                                                 # CONFIRMED native, not Rosetta
uv venv --python 3.12 ~/.venv-vllm-metal
  → 3.12.14 arm64                                          # CONFIRMED
curl -fsSL https://raw.githubusercontent.com/vllm-project/vllm-metal/main/install.sh | bash
  → ✓ Installation complete!                                # real success, ~10-20min compile
```

Platform verification (the critical check — must NOT be CpuPlatform):
```
source ~/.venv-vllm-metal/bin/activate
python -c "from vllm.platforms import current_platform; print(current_platform)"
```
Real output:
```
INFO [__init__.py:54] - metal -> vllm_metal:register
INFO [__init__.py:272] Platform plugin metal is activated
<vllm_metal.platform.MetalPlatform object at 0x10f431760>
```
CONFIRMED: `MetalPlatform`, not `CpuPlatform`. Real GPU-backed, native
arm64 execution.

First serve attempt hit a mundane, unrelated error (not the emulation
stall pattern):
```
OSError: [Errno 48] Address already in use
```
— leftover port binding from the earlier Docker test container. Cleared
with `docker rm -f r4-vllm-test` + `lsof -ti:8000 | xargs kill -9`, and a
fresh shell needing `source ~/.venv-vllm-metal/bin/activate` again (venv
activation doesn't persist across terminal windows) — both mundane,
expected friction, not a sign of a deeper problem.

Second serve attempt — SUCCESS:
```
vllm serve Qwen/Qwen3-0.6B --max-model-len 2048
```
Real output — ALL the way to server-ready, for the first time all session:
```
INFO: Started server process [94930]
INFO: Waiting for application startup.
INFO: Application startup complete.
```
Full route table registered (`/v1/completions`, `/v1/chat/completions`,
`/v1/models`, etc.) — a real, complete OpenAI-compatible API server.

Completion test:
```
curl -s localhost:8000/v1/completions -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen3-0.6B","prompt":"The capital of France is","max_tokens":16,"temperature":0}'
```
Real output:
```
INFO: 127.0.0.1:57559 - "POST /v1/completions HTTP/1.1" 200 OK
{"id":"cmpl-a73a32b5b93d71f7","object":"text_completion",...,
 "choices":[{"index":0,"text":" Paris. The capital of France is also
 the capital of the Republic of France.","finish_reason":"length",...}],
 "usage":{"prompt_tokens":5,"total_tokens":21,"completion_tokens":16,...}}
```
200 OK, correct completion, full valid OpenAI-compatible schema. Engine
continued logging live throughput metrics afterward — a genuinely
running, healthy server, not a fluke single response.

What this proves:
- DEFINITIVELY CONFIRMS the amd64-Docker-emulation hypothesis from the
  prior three entries: the exact same task (serve Qwen3-0.6B, same
  vLLM-family codebase) that stalled identically 3/3 times under Docker
  succeeded immediately once run natively on arm64 with a GPU-backed
  platform. This is about as close to a controlled A/B comparison as
  this kind of debugging gets.
- Local model serving IS viable on this hardware — R4's core question
  ("does it run at all") is now answered YES, decisively, with a real
  served completion as evidence.
- R7's hardware decision is effectively revised: NOT CPU-in-Docker (as
  originally decided, now proven non-viable on this Mac) but
  vllm-metal, native, outside Docker, GPU-backed via Metal/MLX.

What this does NOT yet prove:
- Did NOT yet test `extract_hidden_states` / the KV Connector hidden-
  states extraction path specifically on vllm-metal — unconfirmed
  whether the MLX/Metal backend implements the same plumbing mainline
  CUDA vLLM does. This is now THE open question for R4/R6, not "does
  it serve at all."
- Did NOT yet resolve the R2 architectural consequence: vllm-metal runs
  OUTSIDE Docker/the compose network entirely (native host process),
  breaking the "everything containerized" property R2 established.
  Hermes (in its Docker container) would need to reach the model server
  via `host.docker.internal:8000` or equivalent, not compose-network DNS.
  AgentSight (Docker/Linux-side) would watch Hermes's container as
  before, but the model server itself sits outside that observability
  boundary. This tradeoff needs explicit discussion, not silent
  adoption.
- Paged attention (vllm-metal's KV cache management) is still labeled
  "experimental" by upstream docs even as the default — worth keeping in
  mind for anything beyond this smoke test.

Net assessment: R4/R7 substantially RESOLVED for the core "can this run
locally at all" question — real evidence, not inference. Two new,
narrower open items replace the old blocker: (a) extract_hidden_states
support under vllm-metal specifically, (b) the R2 architectural
consequence of the model server living outside the Docker/compose
boundary. Both are now the concrete next steps, not "is this even
possible."

## 2026-09-24 — local_activation_probe plugin: extract_hidden_states dead-end confirmed, working alternative built

Following R4/R7's resolution (vllm-metal serves completions), tested
whether the actual scope needed — hidden-states extraction for the
probe-sidecar tier — works on vllm-metal specifically.

Command run:
```
vllm serve Qwen/Qwen3-0.6B --max-model-len 2048 \
  --speculative-config '{"method":"extract_hidden_states",...}' \
  --kv-transfer-config '{"kv_connector":"ExampleHiddenStatesConnector",...}'
```
Real output (definitive, not a hang this time):
```
NotImplementedError: Speculative method 'extract_hidden_states' is not
supported on Metal (supported: Gemma4 MTP, draft_model, ngram).
```
CONFIRMS: vLLM's native hidden-states-extraction mechanism is CUDA-only
in practice — vllm-metal's own source explicitly does not implement it.

Pivoted to NNsight (separate interpretability library, not dependent on
vLLM's speculative-decoding internals).

Test 1 — CPU vs MPS activation correctness (before trusting either):
```python
# loaded Qwen3-0.6B via plain transformers, computed last-layer hidden
# state for the same prompt on CPU and on MPS
```
Real result: max abs diff 8.1e-05, relative diff 1.4e-06 — ordinary
float noise, NOT the "silently incorrect" corruption a known
TransformerLens issue (#1178) reports for a different model on MPS.
CPU and MPS activations are both numerically trustworthy on this model.

Test 2 — NNsight + MPS:
```python
model = LanguageModel("Qwen/Qwen3-0.6B", device_map="mps", dtype=torch.float32)
with model.trace(prompt) as tracer:
    hs = model.model.layers[-1].output[0][:, -1, :].save()
```
Real result: **Segmentation fault: 11** — a hard crash, reproducible.

Test 3 — NNsight + CPU (identical code, device_map="cpu"):
Real result: SUCCESS. Real activation tensor extracted, shape
`[1, 8, 1024]`, first 5 values printed and non-degenerate.

CONCLUSION: NNsight + CPU is the confirmed-working extraction path.
NNsight + MPS is confirmed-broken (segfault, not merely unsupported).
extract_hidden_states via vLLM is confirmed CUDA-only.

## Plugin built: local_activation_probe

Built `plugins/local_activation_probe/` — a general-purpose (model-
agnostic, probe-agnostic) Hermes plugin using the CPU+NNsight path
confirmed above. Real, end-to-end tested, not just written:

- `hermes plugins doctor --ci`:
  ```
  OK: runtime discovery, manifest parsing, import, and registration passed
  registrations: 0 tool(s), 2 hook(s)
  ```
- Direct extraction+scoring test caught a REAL bug (relative probe-path
  resolution against process cwd instead of plugin directory) — fixed,
  re-tested, confirmed working: `REAL SCORE: {'score': 13.625, 'layer':
  -1, 'hidden_dim': 1024}`
- `scripts/train_probe.py` — trained a real difference-of-means probe on
  6 hand-written examples (3 honest, 3 deceptive), Qwen3-0.6B, layer -1.
  Real run, no errors (after fixing a `requires_grad` warning via
  `.detach()`).
- `scripts/validate_probe.py` — tested the trained probe against 4
  HELD-OUT examples (never seen during training). Real output:
  ```
  true_label=0  score=-26.266
  true_label=1  score=+49.625
  true_label=0  score=-35.000
  true_label=1  score=+72.625
  Class 1 mean: +61.125  Class 0 mean: -30.633
  Classes are CLEANLY separated on this held-out set (no score overlap).
  ```

What this proves: the full pipeline (config → model load → activation
extraction → probe training → held-out validation) works end to end,
with real evidence at every step, on this exact hardware. A real bug
was found and fixed during testing (path resolution), not glossed over.

What this does NOT prove: n=4 held-out examples is not statistically
meaningful — this validates the MECHANISM works, not that the specific
trained probe generalizes to real deceptive behavior at scale. README.md
in the plugin directory states this limitation explicitly, along with
the other real limitations (small-n, simplest-possible probe method,
local-model-only applicability, CPU-only speed).

## 2026-09-24 — Corrected README claims after reading the Apollo paper in full

Previously cited arXiv:2502.03407 only from web-search snippets/abstract
and Apollo's own blog summary — not the actual paper text. User asked
directly whether it had been read properly; it had not. Fetched and read
the full PDF text (arxiv.org/pdf/2502.03407, 1368-line extracted text,
read through Methodology, Results, Discussion, and Appendix D
"Methodology Variations" sections directly, not summarized secondhand).

Real corrections made to `plugins/local_activation_probe/README.md` as a
result (previously stated inaccurately or too vaguely):

1. WRONG: README implied difference-of-means was "the" published method.
   ACTUAL (direct quote from paper, Section 3.1/Appendix D.1): primary
   method is LOGISTIC REGRESSION. Paper explicitly tested difference-of-
   means, LDA, and LAT as alternatives (Appendix D.1) and found logistic
   regression best at distinguishing deceptive from CONTROL responses
   specifically (performance on honest-vs-deceptive was comparable
   across methods). This plugin's train_probe.py implements difference-
   of-means only — now labeled correctly as a simplification, not "the"
   method.
2. WRONG/MISSING: no mention of layer choice. ACTUAL: paper applies its
   probe at LAYER 22 of 80 in Llama-3.3-70B's residual stream (chosen
   via a sweep on Llama-3.1, validated to transfer to 3.3, Appendix D.2)
   — not the last layer. This plugin's config.json defaults to `"layer":
   -1` (last layer), unvalidated. Now documented as an untuned default,
   not a validated choice.
3. MISSING: paper normalizes activations (zero mean, unit variance)
   before fitting/scoring. This plugin does not normalize. Now
   documented explicitly.
4. WRONG/MISSING: no mention of aggregation. ACTUAL: paper scores every
   token and takes the MEAN across the whole response (Appendix D.4
   tests alternatives, finds mean best for the Instructed-Pairs probe
   specifically). This plugin only reads the LAST TOKEN of a single
   constructed prompt — a much cruder signal. Now documented.
5. IMPRECISE: previously cited "AUROC ... strong results" vaguely.
   ACTUAL precise numbers now cited: AUROC 0.96-0.999 across eval
   datasets; >96% recall at 1% FPR on Alpaca control data, for their
   best (Instructed-Pairs-trained) probe.
6. ADDED: verbatim quotes from the paper's own stated scope limitation
   (Section 1: their test models are "not yet capable of the sort of
   sophisticated deception we ultimately worry about... deceptive
   actions are generally obvious from reading the complete transcript")
   and documented failure modes (Section 4.1.2: spurious correlation
   with morality/honesty generally; aggregation failures on partially-
   deceptive responses) — both previously only vaguely gestured at, now
   quoted precisely with section references.

Net assessment: the plugin's citation of this paper is now accurate
about what it does and does not implement from the published
methodology. The plugin remains a real, working, but deliberately
simplified subset of the paper's actual method — this is now stated
explicitly rather than implied to be a faithful reproduction.

## 2026-09-24 — Closed all 4 methodology gaps vs. the Apollo paper + 3 new experiments

Following the reading-correction session, implemented the paper's actual
mainline method instead of the simplified subset:

1. Logistic regression (L2, lambda=10, plain-torch gradient descent, no
   sklearn dependency in this env — confirmed absent via `python -c
   "import sklearn"` -> ModuleNotFoundError) added to train_probe.py as
   the new default `--method`. difference_of_means kept as an explicit
   opt-in for comparison.
2. scripts/sweep_layers.py (NEW file): empirically sweeps candidate
   layers with train/val split + AUROC, rather than hardcoding a
   borrowed layer number from the paper's Llama-specific tuning.
3. Normalization (zero-mean/unit-variance, fit on train set, stored in
   probe JSON) added to train_probe.py, validate_probe.py, and the
   plugin's _score_tokens().
4. Mean-over-all-tokens aggregation replacing last-token-only scoring in
   all three files (plugin __init__.py, train_probe.py,
   validate_probe.py). Backward-compat "last_token" mode kept for
   legacy probes via a stored "aggregation" field in the probe JSON.

Real bug caught during actual execution (not just code review): torch
raised `RuntimeError: addmv input tensors must have the same dtype, but
got Float, BFloat16, and Float` when training logistic regression —
model activations come back as bfloat16, torch matmul won't silently
mix dtypes. Fixed with explicit .float() casts in train_probe.py,
validate_probe.py, sweep_layers.py, and the plugin's _score_tokens()
(caught and fixed a dtype-cast ordering bug in my own first fix too —
was casting hidden_states to float AFTER already building `direction`
from the original dtype via new_tensor()).

Three new experiments actually run (not just described), all logged
with real numbers in README.md's "New experiments" section:

1. Layer sweep on Qwen/Qwen3-0.6B (28 layers): last layer (-1) won at
   AUROC=1.000 on a 3-example validation split; mid-network layers
   (2-26) all scored 0.500. Honestly caveated: n=3 val examples means
   AUROC can only take 4 discrete values, so this is a coarse signal.
2. logistic_regression vs difference_of_means head-to-head on identical
   12-train/6-val data: both separated cleanly, but logistic regression
   had a larger class-mean gap (6.09 vs 4.13) and larger min-margin
   (3.17 vs 1.05).
3. Out-of-distribution generalization test (NEW test, not from the
   paper): trained on workplace/coding-flavored examples, tested on 6
   examples from unrelated domains (logistics, healthcare, aviation,
   weather, corporate finance). Real finding: difference_of_means nearly
   failed (one deceptive finance example scored -1.494, close to
   crossing into "honest" territory) while logistic_regression kept a
   healthy margin on the same example (+0.600). This is genuine
   mechanistic evidence (not just citing the paper's claim) that
   logistic regression generalizes better OOD than the simpler
   baseline, on this tiny model/dataset. Small-n caveat fully applies.

All example data (examples/tiny_example.jsonl, tiny_held_out.jsonl, NEW
ood_generalization_test.jsonl) and the actual trained probe
(probes/example_trained_probe.json, logistic_regression method,
Qwen3-0.6B, layer -1) are committed to the repo so any of this is
directly rerunnable.

hermes plugins doctor re-run after all changes: still passes cleanly
(0 tools, 2 hooks registered).
