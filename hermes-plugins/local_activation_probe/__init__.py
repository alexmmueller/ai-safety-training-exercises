"""
local_activation_probe — Hermes plugin

Observes activations of a LOCAL open-weight model during real agent use,
and scores them against a linear probe for deception/misalignment
signals. Model-agnostic and probe-agnostic: point it at any local
HuggingFace model and any probe you've trained, or use the bundled
placeholder probe as a starting point.

STATUS: real, tested extraction mechanism (NNsight + transformers,
CPU-only — see plugin.yaml for why CPU, not MPS/GPU). The bundled
placeholder probe direction is a RANDOM projection, not a trained
classifier — it produces a NUMBER, not a validated deception signal.
Train your own probe (scripts/train_probe.py) before trusting any score.

OBSERVE-ONLY: this plugin never blocks, modifies, or approves a tool
call. It logs a score. Interpreting/acting on that score is on you.
"""

import datetime
import json
import os
import pathlib
import threading
from typing import Any

CONFIG_PATH = pathlib.Path(
    os.environ.get("LOCAL_PROBE_CONFIG", pathlib.Path(__file__).parent / "config.json")
)
LOG_PATH = pathlib.Path(
    os.environ.get("LOCAL_PROBE_LOG", pathlib.Path.home() / ".hermes" / "local_activation_probe.jsonl")
)

_write_lock = threading.Lock()
_state: dict[str, Any] = {"model": None, "probe": None, "config": None, "load_error": None}


def _log(record: dict) -> None:
    record["_logged_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            with LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass


def _load_config() -> dict:
    plugin_dir = pathlib.Path(__file__).parent
    default = {
        "enabled": False,  # OFF by default — user must opt in with a real local model
        "model_name": "Qwen/Qwen3-0.6B",
        "layer": -1,  # index into model's transformer layers; -1 = last
        "device": "cpu",  # DO NOT change to mps — confirmed segfault, see plugin.yaml
        "probe_weights_path": str(plugin_dir / "probes" / "placeholder_probe.json"),
        "score_threshold_log_level": 0.0,  # scores are logged regardless; this is a future hook for alerting
    }
    if CONFIG_PATH.exists():
        try:
            user_cfg = json.loads(CONFIG_PATH.read_text())
            default.update(user_cfg)
        except Exception as e:
            _log({"event": "config_load_error", "error": str(e)})

    # Resolve probe_weights_path relative to the plugin directory if it's
    # not already absolute — config.json ships a relative path
    # ("probes/placeholder_probe.json") for portability, but relative
    # paths must not be resolved against the process's cwd (which varies
    # depending on how/where Hermes was launched).
    probe_path = pathlib.Path(default["probe_weights_path"])
    if not probe_path.is_absolute():
        default["probe_weights_path"] = str(plugin_dir / probe_path)

    return default


def _lazy_load(config: dict):
    """Load the model and probe on first use, not at plugin-register time.
    register(ctx) must be fast and must not block Hermes startup on a
    multi-GB model download/load."""
    if _state["model"] is not None or _state["load_error"] is not None:
        return

    if config["device"] != "cpu":
        _state["load_error"] = (
            f"device={config['device']!r} is not supported — NNsight on MPS "
            "segfaults on this model family (confirmed 2026-09-24, nnsight "
            "0.7.0 / torch 2.14 / macOS). Set device to 'cpu' in config.json."
        )
        _log({"event": "load_error", "error": _state["load_error"]})
        return

    try:
        import torch  # noqa: F401 — imported lazily so a missing dependency
        from nnsight import LanguageModel

        model = LanguageModel(config["model_name"], device_map="cpu")
        probe = _load_probe(config["probe_weights_path"])
        _state["model"] = model
        _state["probe"] = probe
        _state["config"] = config
        _log({"event": "model_loaded", "model_name": config["model_name"], "layer": config["layer"]})
    except Exception as e:
        _state["load_error"] = f"{type(e).__name__}: {e}"
        _log({"event": "load_error", "error": _state["load_error"]})


def _load_probe(path: str):
    """A probe is a direction vector + bias, plus optional normalization
    stats (mean/std per-dimension, computed on the training set) and an
    aggregation method. Stored as plain JSON so it's inspectable and
    framework-agnostic. Matches Apollo Research's linear probe shape
    (arXiv:2502.03407): logistic-regression-fit direction, applied to
    normalized activations, aggregated via mean-over-tokens."""
    import json as _json

    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Probe weights not found at {path}. Run scripts/train_probe.py "
            "to train one on your own model + labeled examples, or point "
            "probe_weights_path at an existing probe."
        )
    data = _json.loads(p.read_text())
    return {
        "direction": data["direction"],
        "bias": data.get("bias", 0.0),
        "normalize": data.get("normalize"),  # {"mean": [...], "std": [...]} or None for legacy probes
        "aggregation": data.get("aggregation", "last_token"),  # legacy probes default to old behavior
        "meta": data.get("meta", {}),
    }


def _score_tokens(hidden_states, probe: dict) -> float:
    """hidden_states: [T, D] per-token activations for one response.
    Applies the probe's stored normalization (if present), scores every
    token, then aggregates per probe['aggregation'] — 'mean_all_tokens'
    matches the paper's mainline method (Appendix D.4); 'last_token' is
    kept only for backward compatibility with probes trained before this
    plugin implemented per-token scoring."""
    hidden_states = hidden_states.float()  # model activations may be bfloat16
    direction = hidden_states.new_tensor(probe["direction"])
    bias = probe["bias"]

    if probe.get("normalize"):
        mean = hidden_states.new_tensor(probe["normalize"]["mean"])
        std = hidden_states.new_tensor(probe["normalize"]["std"])
        hidden_states = (hidden_states - mean) / std

    per_token_scores = hidden_states @ direction + bias  # [T]

    if probe.get("aggregation") == "last_token":
        return float(per_token_scores[-1].item())
    return float(per_token_scores.mean().item())  # mean_all_tokens (mainline, matches paper)


def _extract_and_score(prompt_text: str) -> dict:
    config = _state["config"]
    model = _state["model"]
    probe = _state["probe"]

    layer_idx = config["layer"]
    with model.trace(prompt_text) as tracer:
        layer_out = model.model.layers[layer_idx].output
        saved = layer_out.save()

    tensor = saved[0] if isinstance(saved, tuple) else saved
    all_token_hs = tensor[0] if tensor.dim() == 3 else tensor  # [T, D]
    score = _score_tokens(all_token_hs, probe)
    return {"score": score, "layer": layer_idx, "hidden_dim": all_token_hs.shape[-1], "n_tokens": all_token_hs.shape[0]}


def _pre_tool_call(**kwargs):
    config = _load_config()
    if not config["enabled"]:
        return None  # plugin is opt-in; no-op unless explicitly enabled

    _lazy_load(config)
    if _state["load_error"]:
        _log({"event": "pre_tool_call_skipped", "reason": _state["load_error"]})
        return None  # NEVER block on a probe failure — observe-only, fail open

    tool_name = kwargs.get("tool_name", "")
    args = kwargs.get("args", {})
    # Build a text representation of what the model is about to do — this
    # is a deliberately simple heuristic (stringify the tool call), not a
    # claim that it captures full context. Improving this prompt
    # construction is the most impactful place to extend this plugin.
    prompt_text = f"About to call tool {tool_name!r} with args {args!r}. Was this decision deceptive?"

    try:
        result = _extract_and_score(prompt_text)
        _log({
            "event": "pre_tool_call_score",
            "tool_name": tool_name,
            "score": result["score"],
            "layer": result["layer"],
        })
    except Exception as e:
        _log({"event": "score_error", "tool_name": tool_name, "error": f"{type(e).__name__}: {e}"})

    return None  # ALWAYS observe-only — never blocks, modifies, or approves


def _post_tool_call(**kwargs):
    return None  # reserved for future use (e.g. scoring the tool's output)


def register(ctx):
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("post_tool_call", _post_tool_call)
    _log({"event": "plugin_registered", "pid": os.getpid()})
