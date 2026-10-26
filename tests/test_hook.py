"""SessionEnd hook contract tests. Uses a fake CLI that records its argv, so no real logs or ccusage."""
import importlib.util, json, os, shutil, subprocess, sys, tempfile, threading, time, unittest, venv
from unittest import mock

HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks-handlers", "session_end.py")
SID = "11111111-1111-4111-8111-111111111111"

_spec = importlib.util.spec_from_file_location("session_end", HOOK)
session_end = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(session_end)


class HookFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self.tmp, "cfg"); os.makedirs(self.cfg)
        self.data = os.path.join(self.tmp, "data")
        self.calls = os.path.join(self.tmp, "calls.jsonl")
        self.fake = self.write_fake(os.path.join(self.tmp, "fake_cli.py"))
        self.transcript = os.path.join(self.tmp, "t.jsonl")
        open(self.transcript, "w").write("{}\n")

    def write_fake(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("import json,os,sys\n"
                    f"open({self.calls!r},'a').write(json.dumps({{'argv':sys.argv[1:],'exe':sys.executable,"
                    "'in_hook':os.environ.get('SESSION_RECEIPT_IN_HOOK')})+'\\n')\n")
        return path

    def hook_env(self, env_extra=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("SESSION_RECEIPT")}
        env.update(SESSION_RECEIPT_CONFIG_DIR=self.cfg, SESSION_RECEIPT_DATA_DIR=self.data,
                   SESSION_RECEIPT_CMD=json.dumps([sys.executable, self.fake]), SESSION_RECEIPT_STABLE_S="0.5",
                   SESSION_RECEIPT_MAX_WAIT_S="5")
        env.update(env_extra or {})
        return env

    def event(self):
        return {"session_id": SID, "transcript_path": self.transcript,
                "hook_event_name": "SessionEnd", "reason": "other"}

    def run_hook(self, env_extra=None, event=None, timeout=10):
        ev = event if event is not None else self.event()
        t0 = time.monotonic()
        r = subprocess.run([sys.executable, HOOK], input=json.dumps(ev), env=self.hook_env(env_extra),
                           capture_output=True, text=True, timeout=timeout)
        return r, time.monotonic() - t0

    def calls_made(self):
        return [json.loads(l) for l in open(self.calls)] if os.path.exists(self.calls) else []

    def wait_for_calls(self, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.calls_made():
            time.sleep(0.1)
        return self.calls_made()

    def keep_writing(self, seconds):
        """Append to the transcript for `seconds` (the worker waits until it stops changing)."""
        stop = time.monotonic() + seconds
        def writer():
            while time.monotonic() < stop:
                with open(self.transcript, "a") as f:
                    f.write('{"late":1}\n')
                time.sleep(0.1)
        th = threading.Thread(target=writer); th.start()
        return th

    def log(self):
        return open(os.path.join(self.data, "hook.log")).read()


class HookTest(HookFixture):
    def test_inert_by_default(self):
        r, _ = self.run_hook({"SESSION_RECEIPT_FOREGROUND": "1"})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.calls_made(), [])

    def test_enabled_by_file_runs_cli_with_session_id(self):
        open(os.path.join(self.cfg, "auto-enabled"), "w").close()
        r, _ = self.run_hook({"SESSION_RECEIPT_FOREGROUND": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        c = self.calls_made()
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["argv"][:3], ["session", "--id", SID])
        self.assertEqual(c[0]["in_hook"], "1")  # the CLI knows it runs inside the hook

    def test_disabled_file_wins_over_env(self):
        open(os.path.join(self.cfg, "disabled"), "w").close()
        self.run_hook({"SESSION_RECEIPT_AUTO": "1", "SESSION_RECEIPT_FOREGROUND": "1"})
        self.assertEqual(self.calls_made(), [])

    def test_no_recursion_when_nested(self):
        self.run_hook({"SESSION_RECEIPT_AUTO": "1", "SESSION_RECEIPT_FOREGROUND": "1", "SESSION_RECEIPT_IN_HOOK": "1"})
        self.assertEqual(self.calls_made(), [])

    def test_rejects_unexpected_session_id(self):
        self.run_hook({"SESSION_RECEIPT_AUTO": "1", "SESSION_RECEIPT_FOREGROUND": "1"},
                      event={"session_id": "x; rm -rf /", "transcript_path": self.transcript})
        self.assertEqual(self.calls_made(), [])
        self.assertIn("unexpected session_id", open(os.path.join(self.data, "hook.log")).read())

    def test_malformed_stdin_is_harmless(self):
        env = dict(os.environ, SESSION_RECEIPT_AUTO="1", SESSION_RECEIPT_CMD=json.dumps([sys.executable, self.fake]))
        r = subprocess.run([sys.executable, HOOK], input="not json", env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.calls_made(), [])

    def test_missing_transcript_writes_no_receipt(self):
        os.remove(self.transcript)
        self.run_hook({"SESSION_RECEIPT_AUTO": "1", "SESSION_RECEIPT_FOREGROUND": "1"})
        self.assertEqual(self.calls_made(), [])
        self.assertIn("transcript missing or still changing", open(os.path.join(self.data, "hook.log")).read())

    def test_transcript_still_changing_past_max_wait_writes_no_receipt(self):
        stop_writing = time.monotonic() + 3.0
        def writer():
            while time.monotonic() < stop_writing:
                with open(self.transcript, "a") as f:
                    f.write('{"late":1}\n')
                time.sleep(0.1)
        th = threading.Thread(target=writer); th.start()
        self.run_hook({"SESSION_RECEIPT_AUTO": "1", "SESSION_RECEIPT_FOREGROUND": "1",
                       "SESSION_RECEIPT_MAX_WAIT_S": "1.5"})
        th.join()
        self.assertEqual(self.calls_made(), [])
        self.assertIn("still changing after 1.5s; skipped", open(os.path.join(self.data, "hook.log")).read())

    def test_detached_returns_fast_then_waits_for_stable_transcript(self):
        """The hook returns well inside the 1.5 s budget while the transcript is still being written;
        the CLI runs only after writes stop (incomplete-write guard)."""
        stop_writing = time.monotonic() + 1.5
        def writer():
            while time.monotonic() < stop_writing:
                with open(self.transcript, "a") as f:
                    f.write('{"late":1}\n')
                time.sleep(0.1)
        th = threading.Thread(target=writer); th.start()
        r, elapsed = self.run_hook({"SESSION_RECEIPT_AUTO": "1"})
        self.assertEqual(r.returncode, 0)
        self.assertLess(elapsed, 0.5)
        self.assertEqual(self.calls_made(), [])  # nothing yet: still writing
        th.join()
        last_write = os.stat(self.transcript).st_mtime
        for _ in range(60):
            if self.calls_made():
                break
            time.sleep(0.1)
        self.assertEqual(len(self.calls_made()), 1)
        self.assertGreaterEqual(os.stat(self.calls).st_mtime, last_write + 0.5 - 0.05)


class CliCmdParsing(unittest.TestCase):
    """SESSION_RECEIPT_CMD forms. Parsed without a shell, so no quoting rules beyond these."""

    def parse(self, value):
        with mock.patch.dict(os.environ, {"SESSION_RECEIPT_CMD": value}):
            return session_end.cli_cmd()

    def test_simple_words_unchanged(self):
        self.assertEqual(self.parse("python3 /opt/sr/cli.py"), ["python3", "/opt/sr/cli.py"])
        self.assertEqual(self.parse("session-receipt"), ["session-receipt"])
        self.assertEqual(self.parse("/opt/sr/bin/session-receipt"), ["/opt/sr/bin/session-receipt"])
        self.assertEqual(self.parse(r"C:\sr\session-receipt.exe"), [r"C:\sr\session-receipt.exe"])

    def test_json_array_keeps_spaces(self):
        argv = ["C:/Users/Jane Doe/sr/.venv/Scripts/python.exe", "-m", "session_receipt", "two words"]
        self.assertEqual(self.parse(json.dumps(argv)), argv)

    def test_windows_setup_value(self):
        # What the README's `ConvertTo-Json -InputObject @($cli) -Compress` stores.
        value = r'["C:\\Users\\Jane Doe\\SR Test\\session receipt\\.venv\\Scripts\\session-receipt.exe"]'
        self.assertEqual(self.parse(value),
                         [r"C:\Users\Jane Doe\SR Test\session receipt\.venv\Scripts\session-receipt.exe"])

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell")
    def test_windows_setup_value_from_powershell(self):
        exe = r"C:\Users\Jane Doe\SR Test\session receipt\.venv\Scripts\session-receipt.exe"
        shells = [s for s in ("powershell", "pwsh") if shutil.which(s)]
        self.assertTrue(shells)
        for shell in shells:
            with self.subTest(shell=shell):
                out = subprocess.run([shell, "-NoProfile", "-Command",
                                      "ConvertTo-Json -InputObject @('%s') -Compress" % exe],
                                     capture_output=True, text=True, check=True).stdout.strip()
                self.assertEqual(self.parse(out), [exe])

    def test_quoted_value_is_one_path_whatever_exists(self):
        for path in ("/tmp/example/Jane Doe/session-receipt.exe",
                     r"C:\Users\Jane Doe\sr\.venv\Scripts\session-receipt.exe"):
            with self.subTest(path=path):
                self.assertEqual(self.parse('"%s"' % path), [path])

    def test_absolute_path_followed_by_more_words_is_rejected(self):
        # Could be one path with spaces, or a program and its arguments: use a JSON array.
        for value in ("/tmp/example/Jane Doe/session-receipt.exe",
                      r"C:\Users\Jane Doe\sr\.venv\Scripts\session-receipt.exe",
                      "C:/Users/Jane Doe/session-receipt.exe",
                      r"\\server\share\Jane Doe\session-receipt.exe",
                      "/usr/bin/python3 /opt/sr/cli.py"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "ambiguous"):
                self.parse(value)

    def test_partial_quotes_are_rejected(self):
        for value in (r'"C:\Users\Jane Doe\python.exe" -m session_receipt', 'python3 "my cli.py"', '""'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parse(value)

    def test_malformed_json(self):
        for value in ("[not json", "[]", '["ok", 3]', '[""]'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parse(value)

    def test_unset_uses_the_bundled_cli(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            argv = session_end.cli_cmd()
        self.assertEqual(argv, [sys.executable, "-c", session_end.BUNDLED, session_end.ROOT])
        out = tempfile.mkdtemp()
        r = subprocess.run(argv + ["demo", "--out", "demo", "--now", "2026-01-06T12:00:00Z"], cwd=out,
                           capture_output=True, text=True, timeout=120)  # from another folder
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(out, "demo", "demo-simple.svg")))


class SpacedCommandLaunch(HookFixture):
    """The worker really launches commands whose executable and arguments contain spaces."""

    @classmethod
    def setUpClass(cls):
        cls.base = os.path.join(tempfile.mkdtemp(), "Jane Doe", "session receipt")
        env_dir = os.path.join(cls.base, ".venv")
        venv.create(env_dir, with_pip=False, symlinks=os.name != "nt")
        cls.python = os.path.join(env_dir, "Scripts", "python.exe") if os.name == "nt" \
            else os.path.join(env_dir, "bin", "python")

    def test_json_command_with_spaced_interpreter_script_and_argument(self):
        script = self.write_fake(os.path.join(self.base, "fake cli %s.py" % os.path.basename(self.tmp)))
        data = os.path.join(self.tmp, "data dir")
        r, _ = self.run_hook({"SESSION_RECEIPT_AUTO": "1", "SESSION_RECEIPT_DATA_DIR": data,
                              "SESSION_RECEIPT_CMD": json.dumps([self.python, script, "two words"])})
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.wait_for_calls()  # detached worker: the real launch path on this OS
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["argv"], ["two words", "session", "--id", SID,
                                            "--out", os.path.join(data, "receipts")])
        self.assertEqual(os.path.normcase(calls[0]["exe"]), os.path.normcase(self.python))

    @unittest.skipIf(os.name == "nt", "a script is not directly executable on Windows; the JSON test covers it")
    def test_quoted_executable_path_with_spaces(self):
        exe = os.path.join(self.base, "bin %s" % os.path.basename(self.tmp), "session-receipt")
        os.makedirs(os.path.dirname(exe))
        with open(exe, "w") as f:
            f.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, self.fake))
        os.chmod(exe, 0o755)
        r, _ = self.run_hook({"SESSION_RECEIPT_AUTO": "1", "SESSION_RECEIPT_FOREGROUND": "1",
                              "SESSION_RECEIPT_CMD": '"%s"' % exe})
        self.assertEqual(r.returncode, 0, self.log())
        self.assertEqual(self.calls_made()[0]["argv"][:3], ["session", "--id", SID])

    def prefix_trap(self):
        """A missing executable at .../example/Jane Doe/session-receipt.exe, and a real one at its
        first-word prefix .../example/Jane (directly executable on POSIX) that must never run."""
        root = os.path.join(self.tmp, "example")
        os.makedirs(root)
        self.prefix_ran = os.path.join(self.tmp, "prefix-ran")
        prefix = os.path.join(root, "Jane")
        with open(prefix, "w") as f:
            f.write('#!/bin/sh\ntouch "%s"\n' % self.prefix_ran)
        os.chmod(prefix, 0o755)
        return os.path.join(root, "Jane Doe", "session-receipt.exe")

    def test_missing_quoted_spaced_path_never_runs_its_prefix(self):
        missing = self.prefix_trap()
        self.run_hook({"SESSION_RECEIPT_AUTO": "1", "SESSION_RECEIPT_FOREGROUND": "1",
                       "SESSION_RECEIPT_CMD": '"%s"' % missing})
        self.assertFalse(os.path.exists(self.prefix_ran))
        self.assertEqual(self.calls_made(), [])
        self.assertIn("could not start %r" % missing, self.log())

    def test_missing_unquoted_spaced_path_never_runs_its_prefix(self):
        missing = self.prefix_trap()
        self.run_hook({"SESSION_RECEIPT_AUTO": "1", "SESSION_RECEIPT_FOREGROUND": "1",
                       "SESSION_RECEIPT_CMD": missing})
        self.assertFalse(os.path.exists(self.prefix_ran))
        self.assertEqual(self.calls_made(), [])
        self.assertIn("SESSION_RECEIPT_CMD is ambiguous", self.log())

    def test_malformed_json_is_logged(self):
        r, _ = self.run_hook({"SESSION_RECEIPT_AUTO": "1", "SESSION_RECEIPT_FOREGROUND": "1",
                              "SESSION_RECEIPT_CMD": "[not json"})
        self.assertEqual(self.calls_made(), [])
        self.assertIn("SESSION_RECEIPT_CMD is not a valid JSON array", self.log())

    def test_missing_executable_is_logged(self):
        missing = os.path.join(self.tmp, "no such dir", "session-receipt.exe")
        self.run_hook({"SESSION_RECEIPT_AUTO": "1", "SESSION_RECEIPT_FOREGROUND": "1",
                       "SESSION_RECEIPT_CMD": json.dumps([missing])})
        self.assertEqual(self.calls_made(), [])
        self.assertIn("could not start %r" % missing, self.log())


PLUGIN = os.path.join(os.path.dirname(__file__), "..")
NODE = shutil.which("node")


def hook_launcher():
    """The exec-form command hooks.json gives Claude Code, with ${CLAUDE_PLUGIN_ROOT} filled in."""
    with open(os.path.join(PLUGIN, "hooks", "hooks.json")) as f:
        h = json.load(f)["hooks"]["SessionEnd"][0]["hooks"][0]
    return [h["command"]] + [a.replace("${CLAUDE_PLUGIN_ROOT}", PLUGIN) for a in h["args"]]


class HooksJsonCommand(unittest.TestCase):
    def test_exec_form_with_node(self):  # no shell, so it runs the same under Git Bash and PowerShell
        argv = hook_launcher()
        self.assertEqual(argv[0], "node")
        self.assertTrue(argv[1].endswith("/hooks-handlers/run_hook.js") and os.path.isfile(argv[1]), argv)


@unittest.skipUnless(NODE, "needs node")
@unittest.skipIf(os.name == "nt", "the fake interpreters are shell scripts; HookLauncherRealPython covers Windows")
class HookInterpreterChoice(unittest.TestCase):
    """run_hook.js starts the first of python3, python, `py -3` that is Python 3.10 or later. Fake
    interpreters on an otherwise empty PATH record what ran; a stub (like the WindowsApps one) fails
    every call."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bin = os.path.join(self.tmp, "bin"); os.makedirs(self.bin)
        self.record = os.path.join(self.tmp, "record")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake(self, name, works=True, flag=None):
        """`flag`: an argument the interpreter must be given first (`py -3`)."""
        body = "echo 'Python was not found' >&2; exit 9\n"
        if works:
            need = '[ "$1" = %s ] || exit 2; shift\n' % flag if flag else ""
            body = (need + 'if [ "$1" = -c ]; then exit 0; fi\n'
                    'read -r line; printf "%%s\\n" "%s $*" "$line" > "$SR_RECORD"\n' % name)
        path = os.path.join(self.bin, name)
        with open(path, "w", newline="\n") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(path, 0o755)

    def run_command(self):
        env = {"PATH": self.bin, "SR_RECORD": self.record}
        r = subprocess.run([NODE] + hook_launcher()[1:], input='{"session_id": "x"}\n', env=env,
                           capture_output=True, text=True, timeout=30)
        ran = None
        if os.path.exists(self.record):
            with open(self.record) as f:
                ran = f.read().splitlines()
        return r, ran

    def assert_ran(self, ran, name):
        self.assertIsNotNone(ran)
        self.assertTrue(ran[0].startswith(name + " "), ran)
        self.assertTrue(ran[0].endswith("/hooks-handlers/session_end.py"), ran)
        self.assertEqual(ran[1], '{"session_id": "x"}')  # the event still reaches the hook on stdin

    def test_python3_first(self):
        self.fake("python3"); self.fake("python")
        r, ran = self.run_command()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_ran(ran, "python3")

    def test_stub_python3_falls_back_to_python(self):
        self.fake("python3", works=False); self.fake("python")
        r, ran = self.run_command()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_ran(ran, "python")

    def test_only_py_launcher(self):
        self.fake("python3", works=False); self.fake("py", flag="-3")
        r, ran = self.run_command()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_ran(ran, "py")

    def test_no_python_says_so(self):
        self.fake("python3", works=False)
        r, ran = self.run_command()
        self.assertIsNone(ran)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no Python 3.10 or later found", r.stderr)


@unittest.skipUnless(NODE, "needs node")
class HookLauncherRealPython(HookFixture):
    """run_hook.js with this machine's real Python, on every OS (Windows included)."""

    def run_launcher(self, path_dirs, env_extra=None):
        env = self.hook_env(env_extra)
        env["PATH"] = os.pathsep.join(path_dirs)
        return subprocess.run([NODE] + hook_launcher()[1:], input=json.dumps(self.event()), env=env,
                              capture_output=True, text=True, timeout=60)

    def test_event_reaches_the_hook(self):
        r = self.run_launcher([os.path.dirname(sys.executable)],
                              {"SESSION_RECEIPT_AUTO": "1", "SESSION_RECEIPT_FOREGROUND": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls_made()[0]["argv"][:3], ["session", "--id", SID])

    def test_no_python_says_so(self):
        r = self.run_launcher([tempfile.mkdtemp()])
        self.assertEqual(r.returncode, 1)
        self.assertIn("no Python 3.10 or later found", r.stderr)
        self.assertEqual(self.calls_made(), [])


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    _k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    _k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _ntdll = ctypes.WinDLL("ntdll")
    _ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)

    class _BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", ctypes.c_ulonglong * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    def _ok(result, what):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error(), what)
        return result

    def _job(flags):
        job = _ok(_k32.CreateJobObjectW(None, None), "CreateJobObjectW")
        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = flags
        _ok(_k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)),  # 9: extended limits
            "SetInformationJobObject")
        return job

KILL_ON_JOB_CLOSE, BREAKAWAY_OK, SILENT_BREAKAWAY_OK = 0x2000, 0x800, 0x1000


@unittest.skipUnless(os.name == "nt", "Windows job objects")
class WindowsJobLifecycle(HookFixture):
    """The hook process is put in a job that kills its processes when the job is closed, as a
    parent that cleans up its children would do, and the job is closed as soon as the hook returns.
    libuv (Node's process layer) gives every child it spawns such a job, with SILENT_BREAKAWAY_OK."""

    def hook_in_job(self, flags, close_when_hook_returns=True):
        job = _job(flags)
        writer = self.keep_writing(1.5)  # keeps the worker waiting after the hook returns
        p = subprocess.Popen([sys.executable, HOOK], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=self.hook_env({"SESSION_RECEIPT_AUTO": "1"}),
                             creationflags=0x4)  # CREATE_SUSPENDED: in the job before it runs
        try:
            _ok(_k32.AssignProcessToJobObject(job, int(p._handle)), "AssignProcessToJobObject")
        finally:
            _ntdll.NtResumeProcess(int(p._handle))
        p.communicate(json.dumps(self.event()), timeout=10)
        if close_when_hook_returns:
            _k32.CloseHandle(job)
        writer.join()
        calls = self.wait_for_calls(timeout=6)
        if not close_when_hook_returns:
            _k32.CloseHandle(job)
        return p.returncode, calls

    def test_libuv_style_job_close_spares_worker(self):
        rc, calls = self.hook_in_job(KILL_ON_JOB_CLOSE | BREAKAWAY_OK | SILENT_BREAKAWAY_OK)
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)

    def test_breakaway_lets_worker_outlive_job_close(self):
        try:  # nested jobs: breakaway also needs every enclosing job (e.g. the CI runner's) to allow it
            subprocess.run([sys.executable, "-c", "pass"], creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB)
        except OSError:
            self.skipTest("this process's own job forbids breakaway")
        rc, calls = self.hook_in_job(KILL_ON_JOB_CLOSE | BREAKAWAY_OK)
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)

    def test_job_forbidding_breakaway_falls_back_and_worker_runs_while_job_lives(self):
        rc, calls = self.hook_in_job(KILL_ON_JOB_CLOSE, close_when_hook_returns=False)
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)

    def test_job_forbidding_breakaway_kills_worker_on_close(self):
        """Known limitation: a kill-on-close job that forbids breakaway takes the worker with it."""
        rc, calls = self.hook_in_job(KILL_ON_JOB_CLOSE)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
