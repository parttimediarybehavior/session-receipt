"""SessionEnd hook contract tests. Uses a fake CLI that records its argv, so no real logs or ccusage."""
import json, os, subprocess, sys, tempfile, threading, time, unittest

HOOK = os.path.join(os.path.dirname(__file__), "..", "session-receipt", "hooks-handlers", "session_end.py")
SID = "11111111-1111-4111-8111-111111111111"


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self.tmp, "cfg"); os.makedirs(self.cfg)
        self.data = os.path.join(self.tmp, "data")
        self.calls = os.path.join(self.tmp, "calls.jsonl")
        self.fake = os.path.join(self.tmp, "fake_cli.py")
        with open(self.fake, "w") as f:
            f.write("import json,os,sys\n"
                    f"open({self.calls!r},'a').write(json.dumps({{'argv':sys.argv[1:],'in_hook':os.environ.get('SESSION_RECEIPT_IN_HOOK')}})+'\\n')\n")
        self.transcript = os.path.join(self.tmp, "t.jsonl")
        open(self.transcript, "w").write("{}\n")

    def run_hook(self, env_extra=None, event=None, timeout=10):
        env = {k: v for k, v in os.environ.items() if not k.startswith("SESSION_RECEIPT")}
        env.update(SESSION_RECEIPT_CONFIG_DIR=self.cfg, SESSION_RECEIPT_DATA_DIR=self.data,
                   SESSION_RECEIPT_CMD=f"{sys.executable} {self.fake}", SESSION_RECEIPT_STABLE_S="0.5",
                   SESSION_RECEIPT_MAX_WAIT_S="5")
        env.update(env_extra or {})
        ev = event if event is not None else {"session_id": SID, "transcript_path": self.transcript,
                                              "hook_event_name": "SessionEnd", "reason": "other"}
        t0 = time.monotonic()
        r = subprocess.run([sys.executable, HOOK], input=json.dumps(ev), env=env, capture_output=True,
                           text=True, timeout=timeout)
        return r, time.monotonic() - t0

    def calls_made(self):
        return [json.loads(l) for l in open(self.calls)] if os.path.exists(self.calls) else []

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
        env = dict(os.environ, SESSION_RECEIPT_AUTO="1", SESSION_RECEIPT_CMD=f"{sys.executable} {self.fake}")
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


if __name__ == "__main__":
    unittest.main()
