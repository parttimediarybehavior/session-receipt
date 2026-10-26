"""Regressions for resumed sessions, unknown prices and transcript stability.

1. A resumed session must be receipted in full, not as the date-window slice used to find it.
2. A Codex model with no known price is "unknown", never $0, and the total is partial/unknown.
"""
import json, os, re, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from session_receipt import ccusage_adapter as ad  # noqa: E402
from tests.support import FIX  # noqa: E402  (fixtures generated into a temp dir)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, body):
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


def compact(rows):
    return "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)


def run_cli(*args):
    out = tempfile.mkdtemp()
    env = dict(os.environ, SESSION_RECEIPT_CACHE_DIR=tempfile.mkdtemp())
    r = subprocess.run([sys.executable, "-m", "session_receipt", *args, "--out", out, "--tz", "UTC"],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    return r, out


def read_outputs(out):
    names = os.listdir(out)
    get = lambda ext: read(os.path.join(out, next(n for n in names if n.endswith(ext))))
    svg = get(".svg")
    return json.loads(get(".json")), " ".join(re.findall(r"<text[^>]*>([^<]*)</text>", svg)), get(".html")


class ResumedSession(unittest.TestCase):
    """Fixture A with its FIRST record (the one carrying the 1000 cache-write tokens) moved to
    Jan 1. Hand count of the full session, from the fixture: fresh 1410, output 680,
    cache writes 1000, cache reads 2500 = 5590. The Jan 4-5 slice alone is 2440."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        shutil.copytree(os.path.join(FIX, "a_simple"), self.d, dirs_exist_ok=True)
        self.p = next(os.path.join(dp, f) for dp, _, fs in os.walk(self.d) for f in fs if f.endswith(".jsonl"))
        rows = [json.loads(x) for x in read(self.p).splitlines() if x.startswith("{") and not x.startswith("{this")]
        rows[0]["timestamp"] = "2026-01-01T10:00:00.000Z"
        write(self.p, compact(rows))

    def receipt(self, *sel):
        r, out = run_cli("session", *sel, "--format", "json,svg,html", "--claude-dir", self.d)
        self.assertEqual(r.returncode, 0, r.stderr)
        return read_outputs(out)[0]["receipts"][0]

    def test_slice_really_is_partial(self):  # guards the fixture itself
        s = ad.fetch_claude_sessions("UTC", "2026-01-04", "2026-01-05", claude_dir=self.d)[0]
        self.assertEqual(s.totals["total_tokens"], 2440)

    def test_latest_equals_id_and_hand_count(self):
        latest = self.receipt("--latest", "--now", "2026-01-05T12:00:00Z")
        by_id = self.receipt("--id", "aaaaaaaa", "--now", "2026-01-05T12:00:00Z")
        for r in (latest, by_id):
            t = r["totals"]
            self.assertEqual([t["input"], t["output"], t["cache_write"], t["cache_read"]], [1410, 680, 1000, 2500])
            self.assertEqual(t["total_tokens"], 5590)
            self.assertTrue(r["window_start"].startswith("2026-01-01"))
        self.assertEqual(latest["totals"], by_id["totals"])

    def test_explicit_window_is_discovery_only(self):
        r = self.receipt("--since", "2026-01-05", "--until", "2026-01-05")
        self.assertEqual(r["totals"]["total_tokens"], 5590)


class CodexUnknownPrice(unittest.TestCase):
    def codex_home(self, mixed):
        d = tempfile.mkdtemp()
        shutil.copytree(os.path.join(FIX, "g_codex", "codex_home"), d, dirs_exist_ok=True)
        p = next(os.path.join(dp, f) for dp, _, fs in os.walk(d) for f in fs if f.endswith(".jsonl"))
        rows = [json.loads(x) for x in read(p).splitlines()]
        if not mixed:
            rows[1]["payload"]["model"] = "mystery-model-unknown-xyz"
        else:
            # second turn switches to an unpriced model and adds 500 fresh + 200 cached input, 50 output
            rows.append({"timestamp": "2026-01-05T12:00:20.000Z", "type": "turn_context",
                         "payload": {"cwd": "/x", "model": "mystery-model-unknown-xyz"}})
            rows.append({"timestamp": "2026-01-05T12:00:30.000Z", "type": "event_msg", "payload": {
                "type": "token_count", "info": {
                    "total_token_usage": {"input_tokens": 3700, "cached_input_tokens": 2100, "output_tokens": 450,
                                          "reasoning_output_tokens": 130, "total_tokens": 4150},
                    "last_token_usage": {"input_tokens": 700, "cached_input_tokens": 200, "output_tokens": 50,
                                         "reasoning_output_tokens": 0, "total_tokens": 750},
                    "model_context_window": 200000}}})
        write(p, compact(rows))
        return d

    def check_outputs(self, out, expect_total_unknown):
        j, visible, html = read_outputs(out)
        r = j["receipts"][0]
        self.assertIn("mystery-model-unknown-xyz", r["unpriced"])
        self.assertTrue(r["totals"]["partial"])
        m = next(m for m in r["models"] if m["name"] == "mystery-model-unknown-xyz")
        self.assertIsNone(m["cost_usd"])
        self.assertIn("partial: excludes 1 unpriced model(s)", visible)
        self.assertNotIn("$0.0000", visible)
        self.assertNotIn("$0.0000", html)
        if expect_total_unknown:
            self.assertIsNone(r["totals"]["cost_usd"])
        return r, visible

    def test_all_unknown_session_and_daily(self):
        home = self.codex_home(mixed=False)
        for args in (["session", "--id", "2026/01/05"], ["daily", "--date", "2026-01-05"]):
            r, out = run_cli(*args, "--source", "codex", "--codex-home", home, "--now", "2026-01-06T12:00:00Z")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.check_outputs(out, expect_total_unknown=True)

    def test_mixed_priced_and_unpriced(self):
        home = self.codex_home(mixed=True)
        r, out = run_cli("session", "--id", "2026/01/05", "--source", "codex", "--codex-home", home,
                         "--now", "2026-01-06T12:00:00Z")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec, visible = self.check_outputs(out, expect_total_unknown=False)
        # the only priced model carries the whole (priced) cost; nothing invented for the other
        gpt = next(m for m in rec["models"] if m["name"] == "gpt-5")
        self.assertEqual(gpt["cost_usd"], rec["totals"]["cost_usd"])
        self.assertGreater(rec["totals"]["cost_usd"], 0)
        self.assertEqual(rec["totals"]["total_tokens"], 3400 + 750)


if __name__ == "__main__":
    unittest.main()
