"""Check ccusage's Codex counts against the rollouts' own per-response usage records.

ccusage 20.0.38 can silently drop a spawned subagent's usage: a subagent rollout with one
response whose `token_count` event is written twice disappears, and with more responses the
first one can be lost. Newer Codex rollouts also write one `token_usage_record` line per response,
so this module adds up those lines and the receipt says how many tokens ccusage did not count.
Counts are never corrected: the receipt keeps ccusage's figures and states the gap.

Only `token_usage_record` lines are parsed, and only their timestamp, response id and token
numbers are kept. Rollouts without such lines (older Codex versions) are "not_checked".
"""
import glob
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

MARKER = b'"token_usage_record"'


def sessions_dir(codex_home=None):
    home = codex_home or os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    return os.path.join(home, "sessions")


def _records(path):
    """(timestamp, input incl. cached + output) per response, once per response id."""
    seen = set()
    try:
        f = open(path, "rb")
    except OSError:
        return
    with f:
        for line in f:
            if MARKER not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            p = o.get("payload") if isinstance(o, dict) else None
            u = p.get("usage") if isinstance(p, dict) else None
            if o.get("type") != "token_usage_record" or not isinstance(u, dict):
                continue
            rid = p.get("response_id")
            if rid is not None:
                if rid in seen:
                    continue
                seen.add(rid)
            try:
                tokens = int(u.get("input_tokens", 0)) + int(u.get("output_tokens", 0))
            except (TypeError, ValueError):
                continue
            yield o.get("timestamp", ""), tokens


def _local_date(ts, tz):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(tz).date().isoformat()
    except (ValueError, AttributeError):
        return None


def _result(log, counted):
    """`counted` is per-file ccusage totals for the files in `log` (absent = 0)."""
    if not log:
        return {"status": "not_checked", "log_tokens": None, "missing_tokens": 0}
    missing = sum(max(0, n - counted.get(f, 0)) for f, n in log.items())
    return {"status": "undercount" if missing else "ok", "log_tokens": sum(log.values()),
            "missing_tokens": missing}


def session_file(r, codex_home=None):
    if r.session_file and os.path.isfile(r.session_file):
        return r.session_file
    p = os.path.join(sessions_dir(codex_home), (r.session_id or "") + ".jsonl")
    return p if os.path.isfile(p) else None


def check_session(r, codex_home=None):
    """Set r.count_check for a Codex session receipt (the full session)."""
    path = session_file(r, codex_home)
    recs = list(_records(path)) if path else []
    log = {path: sum(n for _, n in recs)} if recs else {}
    r.count_check = _result(log, {path: r.totals.get("total_tokens", 0)})
    return r


def day_log(date, tz, codex_home=None):
    """{rollout path: tokens recorded on local `date`} for rollouts that have records that day."""
    z = ZoneInfo(tz)
    out = {}
    for path in glob.glob(os.path.join(sessions_dir(codex_home), "**", "*.jsonl"), recursive=True):
        n = sum(t for ts, t in _records(path) if _local_date(ts, z) == date)
        if n:
            out[os.path.realpath(path)] = n
    return out


def check_daily(r, day_sessions, codex_home=None):
    """Set r.count_check for a Codex daily receipt. `day_sessions` are ccusage's per-session
    receipts restricted to the same day (so each holds that file's usage on that day)."""
    counted = {}
    for s in day_sessions:
        p = session_file(s, codex_home)
        if p:
            counted[os.path.realpath(p)] = s.totals.get("total_tokens", 0)
    r.count_check = _result(day_log(r.window_start, r.tz, codex_home), counted)
    return r
