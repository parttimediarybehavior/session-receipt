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
  then runs `session-receipt session --id <id>` with the bundled CLI (or SESSION_RECEIPT_CMD). If the transcript is missing or still
  changing after MAX_WAIT_S, it writes no receipt and logs why. Output and errors go to
  the data dir.
"""
import json, os, subprocess, sys, time

# The plugin root holds the session_receipt package. BUNDLED runs its CLI from there: it puts ROOT
# first on sys.path in place of the working directory, so a file in the user's project cannot
# shadow a module.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = "import sys; sys.path[0] = sys.argv.pop(1); from session_receipt.cli import main; sys.exit(main())"
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


def _looks_absolute(word):
    """Syntax only, the same on every OS: /x, \\x, \\\\server\\share, C:\\x, C:/x."""
    return word[:1] in ("/", "\\") or (len(word) > 2 and word[0].isalpha() and word[1] == ":"
                                        and word[2] in "/\\")


def cli_cmd():
    """The argv prefix that runs the CLI. Never run through a shell, and decided by syntax alone,
    never by which files exist. SESSION_RECEIPT_CMD is one of:
    - a JSON array of strings (recommended): ["C:\\\\Users\\\\Jane Doe\\\\.venv\\\\Scripts\\\\session-receipt.exe"]
    - the whole value in double quotes: one executable path, used as is, no arguments
    - one word: an executable name or path without spaces
    - several words, the first not an absolute path: split on whitespace (python3 /opt/sr/cli.py)
    Unset: the CLI bundled with this hook, run by this same Python. Raises ValueError for anything
    else, including an absolute path followed by more words, which could be a path with spaces (use
    a JSON array)."""
    cmd = os.environ.get("SESSION_RECEIPT_CMD", "").strip()
    if not cmd:
        return [sys.executable, "-c", BUNDLED, ROOT]
    if cmd.startswith("["):
        try:
            argv = json.loads(cmd)
        except ValueError as e:
            raise ValueError(f"SESSION_RECEIPT_CMD is not a valid JSON array ({e})")
        if not (isinstance(argv, list) and argv and all(isinstance(a, str) and a for a in argv)):
            raise ValueError("SESSION_RECEIPT_CMD must be a JSON array of non-empty strings")
        return argv
    if len(cmd) > 1 and cmd[0] == cmd[-1] == '"' and '"' not in cmd[1:-1]:
        if not cmd[1:-1].strip():
            raise ValueError("SESSION_RECEIPT_CMD is an empty quoted path")
        return [cmd[1:-1]]
    if '"' in cmd:
        raise ValueError("SESSION_RECEIPT_CMD has double quotes that do not wrap the whole value; "
                         "use a JSON array")
    words = cmd.split()
    if len(words) > 1 and _looks_absolute(words[0]):
        raise ValueError("SESSION_RECEIPT_CMD is ambiguous: an absolute path followed by more words "
                         "may be a path with spaces; use a JSON array")
    return words


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
    try:
        cmd, cmd_error = cli_cmd(), None
    except ValueError as e:
        cmd, cmd_error = None, str(e)
    with open(log, "a") as fh:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if cmd_error:
            fh.write(f"{stamp} {cmd_error}; skipped\n")
            return 3
        if not sid or not all(c.isalnum() or c == "-" for c in sid):
            fh.write(f"{stamp} missing or unexpected session_id; skipped\n")
            return 4
        if not stable:  # never present a possibly incomplete transcript as a normal receipt
            fh.write(f"{stamp} transcript missing or still changing after {MAX_WAIT_S:g}s; skipped "
                     f"(run `session-receipt session --id {sid}` later)\n")
            return 5
        full = cmd + ["session", "--id", sid, "--out", out]
        # CREATE_NO_WINDOW (Windows only; 0 elsewhere): a detached worker has no console, so a
        # console child would otherwise pop up a window of its own.
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=300,
                               env=dict(os.environ, SESSION_RECEIPT_IN_HOOK="1"),
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:  # e.g. a SESSION_RECEIPT_CMD path that does not exist
            fh.write(f"{stamp} could not start {cmd[0]!r}: {e}; skipped\n")
            return 6
        fh.write(f"{stamp} reason={event.get('reason')} transcript_stable={stable} rc={r.returncode}\n")
        if r.returncode:
            fh.write(r.stderr[-2000:] + "\n")
        return r.returncode


def spawn_worker(event):
    """Windows has no fork: start this script again as a detached worker, event passed in env."""
    env = dict(os.environ, SESSION_RECEIPT_IN_HOOK="1", SESSION_RECEIPT_HOOK_EVENT=json.dumps(event))
    argv = [sys.executable, os.path.abspath(__file__), "--worker"]
    kw = dict(env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, close_fds=True)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:  # leave Claude Code's job object where allowed, so the worker outlives the hook
        subprocess.Popen(argv, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw)
    except OSError:
        subprocess.Popen(argv, creationflags=flags, **kw)


def main():
    if sys.argv[1:] == ["--worker"]:  # detached Windows worker started by spawn_worker()
        return worker(json.loads(os.environ.pop("SESSION_RECEIPT_HOOK_EVENT", "{}")))
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
    if os.name == "nt":
        spawn_worker(event)
        return 0
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
