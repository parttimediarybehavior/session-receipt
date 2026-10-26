"""Check ccusage's Codex counts against the rollouts' own per-response usage records.

ccusage 20.0.38 to 20.0.44 can silently drop a spawned subagent's usage (ccusage/ccusage#1970):
a subagent rollout with one response whose `token_count` event is written twice disappears, and
with more responses the first one can be lost. Newer Codex rollouts also write one
`token_usage_record` line per response, so this module adds up those lines and the receipt says
how far ccusage's count is from them. Counts are never corrected: the receipt keeps ccusage's
figures and states the gap.

Only `token_usage_record` lines are parsed, and only their timestamp, response id and token
numbers are kept. A record that is not well formed is skipped and counted, never fatal.

Status, worst first:
  undercount   the logs record tokens that ccusage did not count;
  mismatch     ccusage counted more than the records show (they may cover only part of the usage);
  incomplete   some nearby records could not be read or dated, so the check is not complete;
  ok           ccusage and the records agree;
  not_checked  no records to compare (older Codex versions).
"""
import glob
import json
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MARKER = b'"token_usage_record"'
_FRACTION = re.compile(r"(\.\d+)")


def sessions_dir(codex_home=None):
    home = codex_home or os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    return os.path.join(home, "sessions")


def _count(v):
    """A token count: a plain non-negative int (not bool, float, string or negative)."""
    return v if type(v) is int and v >= 0 else None


def parse_time(ts):
    """ISO 8601 UTC timestamp -> aware datetime, or None. Accepts any fraction length (3.10 cannot)."""
    if not isinstance(ts, str):
        return None
    s = _FRACTION.sub(lambda m: (m.group(1) + "000000")[:7], ts.strip().replace("Z", "+00:00"), count=1)
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, OverflowError, OSError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class FileRecords:
    """One rollout's usage records: good (time, tokens) pairs plus counts of what was skipped."""

    def __init__(self, path):
        self.path, self.good, self.malformed, self.undated = path, [], 0, 0
        seen = set()
        try:
            f = open(path, "rb")
        except OSError:
            self.malformed += 1
            return
        with f:
            for line in f:
                if MARKER not in line:
                    continue
                try:
                    o = json.loads(line)
                except (ValueError, RecursionError):
                    self.malformed += 1
                    continue
                if not isinstance(o, dict) or o.get("type") != "token_usage_record":
                    continue  # the marker text inside some other line
                p = o.get("payload")
                u = p.get("usage") if isinstance(p, dict) else None
                rid = p.get("response_id") if isinstance(p, dict) else None
                inp = _count(u.get("input_tokens")) if isinstance(u, dict) else None
                out = _count(u.get("output_tokens")) if isinstance(u, dict) else None
                if inp is None or out is None or not (rid is None or isinstance(rid, str)):
                    self.malformed += 1
                    continue
                if rid is not None:
                    if rid in seen:
                        continue
                    seen.add(rid)
                when = parse_time(o.get("timestamp"))
                if when is None:
                    self.undated += 1
                self.good.append((when, inp + out))

    @property
    def total(self):
        return sum(n for _, n in self.good)

    @property
    def skipped(self):
        return self.malformed + self.undated

    def on_day(self, date, tz):
        return sum(n for w, n in self.good if w is not None and w.astimezone(tz).date().isoformat() == date)


def _result(log, counted, receipt_total, skipped):
    """`log`: per-file tokens from the records; `counted`: ccusage's per-file tokens (absent = 0)."""
    if not log and not skipped:
        return {"status": "not_checked", "log_tokens": None, "missing_tokens": 0, "extra_tokens": 0,
                "skipped_records": 0}
    log_total = sum(log.values())
    missing = sum(max(0, n - counted.get(f, 0)) for f, n in log.items())
    extra = sum(max(0, counted.get(f, 0) - n) for f, n in log.items())
    if receipt_total is not None:  # also against the total printed on the receipt
        missing = max(missing, log_total - receipt_total)
    status = ("undercount" if missing else "mismatch" if extra else "incomplete" if skipped else "ok")
    return {"status": status, "log_tokens": log_total, "missing_tokens": missing, "extra_tokens": extra,
            "skipped_records": skipped}


def _apply(r, check):
    r.count_check = check
    if check["status"] == "undercount":
        r.totals["partial"] = True  # the counts (and so the cost) are a lower bound
    return r


def session_file(r, codex_home=None):
    if r.session_file and os.path.isfile(r.session_file):
        return r.session_file
    p = os.path.join(sessions_dir(codex_home), (r.session_id or "") + ".jsonl")
    return p if os.path.isfile(p) else None


def check_session(r, codex_home=None):
    """Set r.count_check for a Codex session receipt (the full session)."""
    path = session_file(r, codex_home)
    if not path:
        return _apply(r, _result({}, {}, None, 0))
    fr = FileRecords(path)
    log = {path: fr.total} if fr.good else {}
    return _apply(r, _result(log, {path: r.totals.get("total_tokens", 0)}, None, fr.skipped))


def rollout_matches(rel, ident):
    """Does a rollout's path under sessions/ (without .jsonl) start with session id `ident`?
    Ids use "/"; relpath uses "\\" on Windows, so both are compared with "/"."""
    return rel.replace("\\", "/").startswith(ident.replace("\\", "/"))


def uncounted_session(ident, codex_home=None):
    """Tokens recorded in a rollout that ccusage did not list at all, matched by session id prefix."""
    base = sessions_dir(codex_home)
    hits = [p for p in glob.glob(os.path.join(base, "**", "*.jsonl"), recursive=True)
            if rollout_matches(os.path.relpath(p, base)[:-6], ident)]
    return sum(FileRecords(p).total for p in hits) if len(hits) == 1 else 0


def _path_date(path):
    m = re.search(r"(\d{4})[/\\](\d{2})[/\\](\d{2})[/\\][^/\\]+$", path)
    return "-".join(m.groups()) if m else None


def day_log(date, tz, codex_home=None):
    """({rollout path: tokens recorded on local `date`}, skipped records in rollouts near that day)."""
    z = ZoneInfo(tz)
    out, skipped = {}, 0
    for path in glob.glob(os.path.join(sessions_dir(codex_home), "**", "*.jsonl"), recursive=True):
        fr = FileRecords(path)
        n = fr.on_day(date, z)
        if n:
            out[os.path.realpath(path)] = n
        if fr.skipped and (n or _path_date(path) == date):
            skipped += fr.skipped
    return out, skipped


def check_daily(r, day_sessions, codex_home=None):
    """Set r.count_check for a Codex daily receipt. `day_sessions` are ccusage's per-session
    receipts restricted to the same day (so each holds that file's usage on that day)."""
    counted = {}
    for s in day_sessions:
        p = session_file(s, codex_home)
        if p:
            counted[os.path.realpath(p)] = s.totals.get("total_tokens", 0)
    log, skipped = day_log(r.window_start, r.tz, codex_home)
    return _apply(r, _result(log, counted, r.totals.get("total_tokens", 0), skipped))
