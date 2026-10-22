#!/usr/bin/env python3
"""SessionEnd hook: optionally write a receipt for the session that just ended.

Contract (see README "Automatic receipts"):
- INERT unless enabled: env SESSION_RECEIPT_AUTO=1, or a file named `auto-enabled`
  in the config dir ($SESSION_RECEIPT_CONFIG_DIR or ~/.config/session-receipt).
  A file named `disabled` there always wins.
- Returns within milliseconds; the work runs in a detached child (SessionEnd hooks
  share a ~1.5 s budget, and the logs may still be flushing).
- Never calls a model and never starts Claude Code, so it cannot trigger a turn.
  SESSION_RECEIPT_IN_HOOK guards against nested runs.
- The child waits until the transcript file stops changing (incomplete-write guard),
  then runs `session-receipt session --id <id>`. If the transcript is missing or still
  changing after MAX_WAIT_S, it writes no receipt and logs why. Output and errors go to
  the data dir.
"""
import json, os, shutil, subprocess, sys, time

STABLE_S = float(os.environ.get("SESSION_RECEIPT_STABLE_S", "2"))
MAX_WAIT_S = float(os.environ.get("SESSION_RECEIPT_MAX_WAIT_S", "30"))


def config_dir():
    return os.environ.get("SESSION_RECEIPT_CONFIG_DIR") or os.path.expanduser("~/.config/session-receipt")


def data_dir():
    return (os.environ.get("SESSION_RECEIPT_DATA_DIR") or os.environ.get("CLAUDE_PLUGIN_DATA")
            or os.path.expanduser("~/.local/share/session-receipt"))


def enabled():
    c = config_dir()
    if os.path.exists(os.path.join(c, "disabled")):
        return False
    return os.environ.get("SESSION_RECEIPT_AUTO") == "1" or os.path.exists(os.path.join(c, "auto-enabled"))


def cli_cmd():
    cmd = os.environ.get("SESSION_RECEIPT_CMD")
    if cmd:
        return cmd.split()
    exe = shutil.which("session-receipt")
    return [exe] if exe else None


def wait_stable(path):
    """Wait until `path` size+mtime are unchanged for STABLE_S, up to MAX_WAIT_S. Returns True if stable."""
    if not path or not os.path.exists(path):
        return False
    deadline = time.monotonic() + MAX_WAIT_S
    last, since = None, time.monotonic()
    while time.monotonic() < deadline:
        st = os.stat(path)
        sig = (st.st_size, st.st_mtime_ns)
        if sig != last:
            last, since = sig, time.monotonic()
        elif time.monotonic() - since >= STABLE_S:
            return True
        time.sleep(0.25)
    return False


def worker(event):
    sid = event.get("session_id") or ""
    out = os.path.join(data_dir(), "receipts")
    os.makedirs(out, exist_ok=True)
    log = os.path.join(data_dir(), "hook.log")
    stable = wait_stable(event.get("transcript_path"))
    cmd = cli_cmd()
    with open(log, "a") as fh:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if not cmd:
            fh.write(f"{stamp} session-receipt not found on PATH and SESSION_RECEIPT_CMD unset; skipped\n")
            return 3
        if not sid or not all(c.isalnum() or c == "-" for c in sid):
            fh.write(f"{stamp} missing or unexpected session_id; skipped\n")
            return 4
        if not stable:  # never present a possibly incomplete transcript as a normal receipt
            fh.write(f"{stamp} transcript missing or still changing after {MAX_WAIT_S:g}s; skipped "
                     f"(run `session-receipt session --id {sid}` later)\n")
            return 5
        full = cmd + ["session", "--id", sid, "--out", out]
        r = subprocess.run(full, capture_output=True, text=True, timeout=300,
                           env=dict(os.environ, SESSION_RECEIPT_IN_HOOK="1"))
        fh.write(f"{stamp} reason={event.get('reason')} transcript_stable={stable} rc={r.returncode}\n")
        if r.returncode:
            fh.write(r.stderr[-2000:] + "\n")
        return r.returncode


def main():
    if os.environ.get("SESSION_RECEIPT_IN_HOOK") == "1":
        return 0  # nested run: never recurse
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0
    if not enabled():
        return 0
    if os.environ.get("SESSION_RECEIPT_FOREGROUND") == "1":  # tests only
        return worker(event)
    pid = os.fork()
    if pid:  # parent: reap the short-lived intermediate child and return now
        os.waitpid(pid, 0)
        return 0
    # child: new session, then the grandchild does the work
    os.setsid()
    if os.fork() == 0:
        devnull = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(devnull, fd)
        os.environ["SESSION_RECEIPT_IN_HOOK"] = "1"
        try:
            worker(event)
        finally:
            os._exit(0)
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
