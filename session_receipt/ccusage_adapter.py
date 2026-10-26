"""Run the pinned ccusage binary and normalise its JSON into Receipt dataclasses.

No model calls, no network (always --offline).  Raw logs are only ever read by ccusage.
"""
import hashlib
import json
import os
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERRIDES = os.path.join(ROOT, "pricing", "ccusage-overrides.json")
# Keys that would mean prompt/response content or paths leaked into ccusage output.
CONTENT_KEYS = {"message", "content", "prompt", "response", "text"}


class ReceiptError(Exception):
    """A user-facing, expected failure."""


@dataclass
class ModelLine:
    name: str
    input: int = 0            # fresh input (excludes cache)
    output: int = 0           # includes thinking / reasoning
    cache_write: int = 0
    cache_read: int = 0
    reasoning: Optional[int] = None   # Codex only; subset of output, display only, never added
    cost_usd: Optional[float] = None  # None = unknown (never $0)
    price_check: str = "unverified"   # ok | mismatch | unverified
    price_detail: Optional[dict] = None  # on mismatch: effective vs reference rates
    missing: bool = False             # ccusage reported missingPricing for this model


@dataclass
class Receipt:
    kind: str                 # session | daily
    source: str               # claude | codex
    label: str                # public scope text, e.g. "one session"
    tz: str
    window_start: str         # ISO UTC (session) or YYYY-MM-DD (daily)
    window_end: str
    models: list = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    unpriced: list = field(default_factory=list)
    provisional: bool = False
    tool_version: str = ""
    pricing_provenance: dict = field(default_factory=dict)
    # private-only fields (omitted from public exports)
    session_id: Optional[str] = None
    project_path: Optional[str] = None
    session_dir: Optional[str] = None
    session_file: Optional[str] = None

    @property
    def short_id(self):
        return short_id(self.session_id) if self.session_id else None


def short_id(session_id):
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:6]


# Native ccusage builds that can run on each machine type Python reports on Windows. npm installs
# the build for Node's process.arch, which differs from Python's when x64 and ARM64 installs are
# mixed on Windows on Arm. x64 builds run there under emulation; an ARM64 build never runs on x64.
# platform.machine() is the CPU (via WMI) on Python 3.12+, but an emulated x64 Python before 3.12
# reports AMD64 on Arm, so it can refuse a usable ARM64 build; it never picks an unusable one.
WIN_COMPATIBLE = {"arm64": ("arm64", "x64"), "aarch64": ("arm64", "x64"),
                  "amd64": ("x64",), "x86_64": ("x64",)}


def windows_binary(modules, machine):
    """The installed ccusage.exe that runs on `machine`, preferring the native build."""
    path = lambda arch: os.path.join(modules, "@ccusage", "ccusage-win32-" + arch, "bin", "ccusage.exe")
    compatible = WIN_COMPATIBLE.get(machine.lower(), ())
    for arch in compatible:
        if os.path.isfile(path(arch)):
            return path(arch)
    installed = [a for a in ("x64", "arm64") if os.path.isfile(path(a))]
    raise ReceiptError(
        "ccusage binary not found for this machine (%s; runs: %s; installed: %s). Run `npm ci "
        "--prefix \"%s\"` with a Node.js build for this machine, or set SESSION_RECEIPT_CCUSAGE "
        "to a ccusage executable." % (machine, ", ".join(compatible) or "none",
                                      ", ".join(installed) or "none", ROOT))


def _default_binary():
    modules = os.path.join(ROOT, "node_modules")
    if os.name != "nt":
        return os.path.join(modules, ".bin", "ccusage")
    # On Windows .bin/ccusage is a POSIX shell shim. The ccusage npm launcher only forwards argv
    # to its per-platform native binary, so call that .exe directly.
    return windows_binary(modules, platform.machine())


def find_binary():
    env = os.environ.get("SESSION_RECEIPT_CCUSAGE")
    path = env or _default_binary()
    if not (os.path.isfile(path) and os.access(path, os.X_OK)):
        raise ReceiptError(
            "ccusage binary not found at %s. Run `npm ci --prefix \"%s\"` (needs Node.js), or set "
            "SESSION_RECEIPT_CCUSAGE to a ccusage executable. `session-receipt doctor` checks the "
            "whole setup." % (path, ROOT))
    return path


def run_ccusage(args, claude_dir=None, codex_home=None, parse=True):
    """Run ccusage with the given args.  Returns parsed JSON (or stdout text)."""
    cmd = [find_binary()] + list(args)
    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    if claude_dir:
        env["CLAUDE_CONFIG_DIR"] = str(claude_dir)
    if codex_home:
        env["CODEX_HOME"] = str(codex_home)
    try:
        p = subprocess.run(cmd, env=env, capture_output=True, encoding="utf-8", timeout=300)
    except subprocess.TimeoutExpired:
        raise ReceiptError("ccusage timed out")
    if p.returncode != 0:
        msg = (p.stderr or p.stdout).strip()
        raise ReceiptError("ccusage failed (exit %d): %s" % (p.returncode, msg[:500]))
    if not parse:
        return p.stdout
    out = p.stdout
    i = out.find("{")
    if not out.strip() or i < 0:
        raise ReceiptError("ccusage produced no JSON output")
    try:
        data = json.loads(out[i:])
    except ValueError as e:
        raise ReceiptError("ccusage output was not valid JSON: %s" % e)
    _assert_no_content(data)
    return data


def _assert_no_content(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in CONTENT_KEYS:
                raise ReceiptError("unexpected content field %r in ccusage output" % (path + k))
            _assert_no_content(v, path + k + ".")
    elif isinstance(o, list):
        for v in o:
            _assert_no_content(v, path)


def tool_version():
    out = run_ccusage(["--version"], parse=False).strip()
    return out


def _date_arg(d):
    return d.replace("-", "")


def _window_args(since, until):
    a = []
    if since:
        a += ["--since", _date_arg(since)]
    if until:
        a += ["--until", _date_arg(until)]
    return a


def _clean_cost(x):
    if x is None:
        return None
    return 0.0 if x == 0 else float(x)


def _totals(models, tokens_total=None):
    t = {"input": sum(m.input for m in models), "output": sum(m.output for m in models),
         "cache_write": sum(m.cache_write for m in models),
         "cache_read": sum(m.cache_read for m in models)}
    return t


def _claude_models(breakdowns):
    ms = []
    for b in breakdowns:
        missing = bool(b.get("missingPricing"))
        ms.append(ModelLine(
            name=b["modelName"], missing=missing, input=b.get("inputTokens", 0), output=b.get("outputTokens", 0),
            cache_write=b.get("cacheCreationTokens", 0), cache_read=b.get("cacheReadTokens", 0),
            cost_usd=None if missing else _clean_cost(b.get("cost"))))
    return ms


def _finish_claude(r, models, session_cost, ver, prov):
    r.models = models
    r.unpriced = [m.name for m in models if m.cost_usd is None]
    t = _totals(models)
    t["cost_usd"] = round(sum(m.cost_usd for m in models if m.cost_usd is not None), 12)
    t["partial"] = bool(r.unpriced)
    t["total_tokens"] = t["input"] + t["output"] + t["cache_write"] + t["cache_read"]
    r.totals = t
    r.tool_version = ver
    r.pricing_provenance = prov
    return r


def _codex_models(models_dict, session_cost):
    ms = []
    for name, m in models_dict.items():
        ms.append(ModelLine(
            name=name, input=m.get("inputTokens", 0), output=m.get("outputTokens", 0),
            cache_write=m.get("cacheCreationTokens", 0), cache_read=m.get("cacheReadTokens", 0),
            reasoning=m.get("reasoningOutputTokens", 0), missing=bool(m.get("missingPricing")),
            cost_usd=None, price_check="unverified"))
    priced = [x for x in ms if not x.missing]
    # ccusage gives Codex cost per session/day only. Allocate it to a model only when exactly one
    # model is priced (unpriced models contribute nothing to costUSD); never invent a split.
    if len(priced) == 1 and session_cost is not None:
        priced[0].cost_usd = _clean_cost(session_cost)
    return ms


def _finish_codex(r, models, cost, ver, prov, unpriced_hint=()):
    r.models = models
    t = _totals(models)
    t["reasoning"] = sum(m.reasoning or 0 for m in models)
    # Codex: total = fresh input + cache read + output (reasoning already inside output)
    t["total_tokens"] = t["input"] + t["cache_read"] + t["output"]
    # Unknown price is never $0: missingPricing per model (or ccusage's unpricedModels) wins.
    r.unpriced = [m.name for m in models if m.missing or m.name in unpriced_hint]
    priced = [m for m in models if m.name not in r.unpriced]
    t["cost_usd"] = _clean_cost(cost) if priced else None
    t["partial"] = bool(r.unpriced)
    r.totals = t
    r.tool_version = ver
    r.pricing_provenance = prov
    return r


def provenance():
    from . import pricecheck
    ref = pricecheck.load_reference()
    return {"source": ref["source"], "as_of": ref["as_of"], "checked": ref["checked"],
            "overrides_sha256": pricecheck.file_sha256(OVERRIDES)}


def fetch_claude_sessions(tz, since=None, until=None, claude_dir=None, config=OVERRIDES):
    args = ["claude", "session", "--json", "--offline", "-z", tz, "--config", config]
    data = run_ccusage(args + _window_args(since, until), claude_dir=claude_dir)
    ver, prov = tool_version(), provenance()
    out = []
    for s in data.get("sessions", []):
        r = Receipt(kind="session", source="claude", label="one session", tz=tz,
                    window_start=s.get("firstActivity", ""), window_end=s.get("lastActivity", ""),
                    session_id=s["sessionId"], project_path=s.get("projectPath"))
        out.append(_finish_claude(r, _claude_models(s.get("modelBreakdowns", [])),
                                  s.get("totalCost"), ver, prov))
    return out


def fetch_claude_daily(tz, since=None, until=None, claude_dir=None, config=OVERRIDES):
    args = ["claude", "daily", "--json", "--offline", "-z", tz, "--config", config]
    data = run_ccusage(args + _window_args(since, until), claude_dir=claude_dir)
    ver, prov = tool_version(), provenance()
    out = []
    for d in data.get("daily", []):
        r = Receipt(kind="daily", source="claude", label="one day, %s, %s" % (d["date"], tz),
                    tz=tz, window_start=d["date"], window_end=d["date"])
        out.append(_finish_claude(r, _claude_models(d.get("modelBreakdowns", [])),
                                  d.get("totalCost"), ver, prov))
    return out


def fetch_codex_sessions(tz, since=None, until=None, codex_home=None):
    args = ["codex", "session", "--json", "--offline", "-z", tz]
    data = run_ccusage(args + _window_args(since, until), codex_home=codex_home)
    ver, prov = tool_version(), provenance()
    unpriced_hint = set((data.get("totals") or {}).get("unpricedModels") or [])
    out = []
    for s in data.get("sessions", []):
        last = s.get("lastActivity", "")
        r = Receipt(kind="session", source="codex", label="one session", tz=tz,
                    window_start=last, window_end=last, session_id=s["sessionId"],
                    session_dir=s.get("directory"), session_file=s.get("sessionFile"))
        out.append(_finish_codex(r, _codex_models(s.get("models", {}), s.get("costUSD")),
                                 s.get("costUSD"), ver, prov, unpriced_hint))
    return out


def fetch_codex_daily(tz, since=None, until=None, codex_home=None):
    args = ["codex", "daily", "--json", "--offline", "-z", tz]
    data = run_ccusage(args + _window_args(since, until), codex_home=codex_home)
    ver, prov = tool_version(), provenance()
    unpriced_hint = set((data.get("totals") or {}).get("unpricedModels") or [])
    out = []
    for d in data.get("daily", []):
        r = Receipt(kind="daily", source="codex", label="one day, %s, %s" % (d["date"], tz),
                    tz=tz, window_start=d["date"], window_end=d["date"])
        out.append(_finish_codex(r, _codex_models(d.get("models", {}), d.get("costUSD")),
                                 d.get("costUSD"), ver, prov, unpriced_hint))
    return out


def parse_now(s):
    if s is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def mark_provisional(r, now):
    """Provisional if lastActivity is within 2 minutes of `now`, or the window includes today."""
    tz = ZoneInfo(r.tz)
    today = now.astimezone(tz).date().isoformat()
    if r.kind == "daily":
        r.provisional = r.window_end >= today >= r.window_start
        return r
    try:
        last = datetime.fromisoformat(r.window_end.replace("Z", "+00:00"))
    except ValueError:
        return r
    near = abs(now - last) <= timedelta(minutes=2)
    r.provisional = near or last.astimezone(tz).date().isoformat() == today
    return r
