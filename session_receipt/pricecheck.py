"""Deterministic self-test of the EFFECTIVE per-MTok rates ccusage applies.

For each Claude model, write five one-record COMPACT fixtures (input, output, cache
write 5m, cache read, cache write ephemeral_1h) into a temp CLAUDE_CONFIG_DIR, run
ccusage, read the cost, compare with pricing/reference.json.

Each probe uses 50,000 tokens (scaled x20 to USD/MTok),
not 1,000,000.  A 1M-token single message exceeds haiku-5-5's >100K-prompt tier, which
ccusage correctly prices at $0.50/$2.50, producing a false "mismatch" against the
standard-tier reference.
"""
import hashlib
import json
import os
import re
import tempfile

from . import ccusage_adapter as ad

ROOT = ad.ROOT
REFERENCE = os.path.join(ROOT, "pricing", "reference.json")
RATE_KEYS = ("input", "output", "cache_write_5m", "cache_read", "cache_write_1h")
REL_TOL = 1e-6
N = 50_000          # tokens per probe, safely under the 100K tier threshold
SCALE = 1_000_000 // N


def load_reference(path=None):
    with open(path or REFERENCE) as f:
        return json.load(f)


def file_sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def reference_key(model_name, reference_path=None):
    """'claude-sonnet-5-5' / 'claude-sonnet-5-5-20261001' -> 'sonnet-5-5' (if known)."""
    n = model_name[len("claude-"):] if model_name.startswith("claude-") else model_name
    n = re.sub(r"-\d{8}$", "", n)
    return n if n in load_reference(reference_path)["models"] else None


def cache_dir():
    d = os.environ.get("SESSION_RECEIPT_CACHE_DIR")
    if not d:
        d = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                         "session-receipt")
    return d


def _cache_path():
    return os.path.join(cache_dir(), "pricecheck.json")


def _load_cache():
    try:
        with open(_cache_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cache(c):
    try:
        os.makedirs(cache_dir(), exist_ok=True)
        with open(_cache_path(), "w") as f:
            json.dump(c, f, indent=1, sort_keys=True)
    except OSError:
        pass  # caching is an optimisation only


def _probe_record(model, kind):
    usage = {"input_tokens": 0, "output_tokens": 0,
             "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    if kind == "input":
        usage["input_tokens"] = N
    elif kind == "output":
        usage["output_tokens"] = N
    elif kind == "cache_write_5m":
        usage["cache_creation_input_tokens"] = N
    elif kind == "cache_read":
        usage["cache_read_input_tokens"] = N
    elif kind == "cache_write_1h":
        usage["cache_creation_input_tokens"] = N
        usage["cache_creation"] = {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": N}
    return {"type": "assistant", "timestamp": "2026-01-01T00:00:00.000Z",
            "sessionId": "pricecheck-" + kind, "requestId": "req_pc_" + kind,
            "message": {"id": "msg_pc_" + kind, "model": model, "role": "assistant",
                        "usage": usage}}


def measure_effective(model, config=ad.OVERRIDES):
    """Return {rate_key: USD per MTok} as ccusage actually charges it."""
    eff = {}
    for kind in RATE_KEYS:
        with tempfile.TemporaryDirectory(prefix="sr_pc_") as tmp:
            pdir = os.path.join(tmp, "projects", "-pricecheck")
            os.makedirs(pdir)
            with open(os.path.join(pdir, "pc.jsonl"), "w") as f:
                f.write(json.dumps(_probe_record(model, kind), separators=(",", ":")) + "\n")
            data = ad.run_ccusage(["claude", "session", "--json", "--offline", "-z", "UTC",
                                   "--config", config], claude_dir=tmp)
        sessions = data.get("sessions", [])
        if len(sessions) != 1:
            raise ad.ReceiptError("pricecheck probe for %s/%s returned %d sessions"
                                  % (model, kind, len(sessions)))
        bd = sessions[0]["modelBreakdowns"]
        if bd[0].get("missingPricing"):
            eff[kind] = None
        else:
            eff[kind] = float(bd[0]["cost"]) * SCALE  # N tokens -> USD per MTok
    return eff


def check_model(model, config=ad.OVERRIDES, use_cache=True, reference_path=None):
    """Return {status: ok|mismatch|unverified, effective, reference, differing}."""
    reference_path = reference_path or REFERENCE
    key = reference_key(model, reference_path)
    if key is None:
        return {"status": "unverified", "model": model}
    ref_all = load_reference(reference_path)["models"][key]
    ref = {k: ref_all[k] for k in RATE_KEYS}
    ck = "|".join(["probe-v2", ad.tool_version(), model, file_sha256(config), file_sha256(reference_path)])
    cache = _load_cache() if use_cache else {}
    if ck in cache:
        return cache[ck]
    eff = measure_effective(model, config)
    differing = [k for k in RATE_KEYS
                 if eff[k] is None or abs(eff[k] - ref[k]) > REL_TOL * abs(ref[k])]
    res = {"status": "mismatch" if differing else "ok", "model": model,
           "effective": eff, "reference": ref, "differing": differing}
    if use_cache:
        cache[ck] = res
        _save_cache(cache)
    return res


def apply_to_receipt(r, config=ad.OVERRIDES, use_cache=True):
    """Set price_check on each ModelLine (Claude only; Codex stays unverified)."""
    if r.source != "claude":
        return r
    for m in r.models:
        res = check_model(m.name, config, use_cache)
        m.price_check = res["status"]
        if res["status"] == "mismatch":
            m.price_detail = {"effective": res["effective"], "reference": res["reference"],
                              "differing": res["differing"]}
    return r


def summary_status(receipts):
    """Overall status string for the footer."""
    st = [m.price_check for r in receipts for m in r.models]
    if "mismatch" in st:
        return "mismatch"
    if st and all(s == "ok" for s in st):
        return "ok"
    if "ok" in st:
        return "partly verified"
    return "unverified"
