"""
Hermes plugin: observability_bridge

STATUS: UNTESTED. Written against the documented pre_tool_call/post_tool_call
hook API (website/docs/user-guide/features/hooks.md,
docs/observability/README.md) but never actually loaded into a running
Hermes instance. Before trusting this, run it against a real session and
confirm log lines actually appear (see docker-sandbox/docs/VERIFICATION.md in repo root).

Purpose: OBSERVE ONLY. This plugin never returns a block/modify/approve
directive. Its only job is to append a structured JSONL record of every
tool call Hermes's own runtime reports, to a log file, so that a future
`correlator` component can diff Hermes's self-reported events against
AgentSight's independent kernel-level event log. Divergence between the
two logs (e.g. Hermes claims a tool call was blocked but AgentSight saw
the underlying syscalls execute anyway) is the actual security signal —
not this log in isolation.

Known risk (see docs/RISKS.md R3): pre_tool_call has had at least one
production bug (hermes-agent#41045) where hook return values were
silently discarded, and open reports of the hook not firing reliably in
some execution contexts. This plugin returning None/no-op everywhere
sidesteps the "return value discarded" bug class (we never rely on our
return value being honored) but does NOT protect against the hook simply
not firing at all. That failure mode can only be caught by AgentSight's
independent observation, which is the whole point of running both.
"""

import datetime
import json
import os
import pathlib
import threading

LOG_PATH = pathlib.Path(
    os.environ.get("OBSERVABILITY_BRIDGE_LOG", "/var/log/sandbox/hermes_hooks.jsonl")
)

_write_lock = threading.Lock()


def _append(record: dict) -> None:
    """Best-effort append. Never raises — a logging failure must not be
    allowed to affect the agent loop (this plugin is not a security
    control, only a log stream for a downstream correlator)."""
    record["_logged_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            with LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        # Deliberately swallowed. See module docstring: this plugin must
        # never be the thing that breaks the agent loop. If you need to
        # debug why logging is failing, temporarily remove this try/except
        # in a non-production run.
        pass


def _pre_tool_call(**kwargs):
    _append({"event": "pre_tool_call", **kwargs})
    return None  # explicit no-op — never blocks, modifies, or approves


def _post_tool_call(**kwargs):
    _append({"event": "post_tool_call", **kwargs})
    return None  # explicit no-op


def register(ctx):
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("post_tool_call", _post_tool_call)
    _append({"event": "plugin_registered", "pid": os.getpid()})
