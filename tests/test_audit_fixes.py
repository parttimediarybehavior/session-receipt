"""Regressions from the 2026-10-25 real-log audit (all fixtures synthetic).

F1. A Claude receipt whose every model is unpriced has an unknown total (null), not $0.
F2. ccusage 20.0.38 can drop a spawned Codex subagent's usage. The receipt checks its Codex
    counts against the rollout's own per-response `token_usage_record` lines and says how many
    tokens ccusage missed.
F3. Codex subagent threads are separate sessions, so a Codex session receipt must not claim
    "counts include subagents".
"""
import json, os, re, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests.support import CCUSAGE_PRESENT  # noqa: E402

PARENT = "11111111-0000-4000-8000-000000000000"
CHILD = "22222222-0000-4000-8000-000000000000"


def compact(rows):
    return "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)


def usage(inp, cached, out):
    return {"input_tokens": inp, "cached_input_tokens": cached, "cache_write_input_tokens": 0,
            "output_tokens": out, "reasoning_output_tokens": 0, "total_tokens": inp + out}


def rollout(home, tid, parent, records, token_count_repeats=1, start="2026-01-05T15-00-00"):
    """A paginated-format rollout: session_meta, turn_context, then per response one
    token_usage_record followed by `token_count_repeats` identical token_count events."""
    meta = {"id": tid, "session_id": parent or tid, "cwd": "/home/alice/p", "originator": "codex-tui",
            "cli_version": "0.0.0", "model_provider": "openai", "history_mode": "paginated",
            "timestamp": "2026-01-05T15:00:00.000Z"}
    if parent:
        meta.update(parent_thread_id=parent, thread_source="subagent", multi_agent_version="v2",
                    source={"subagent": {"thread_spawn": {"parent_thread_id": parent, "depth": 1, "agent_path": "x",
                                                          "agent_nickname": "x", "agent_role": None}}})
    else:
        meta["source"] = "cli"
    rows = [{"timestamp": "2026-01-05T15:00:00.000Z", "type": "session_meta", "payload": meta},
            {"timestamp": "2026-01-05T15:00:01.000Z", "type": "turn_context",
             "payload": {"model": "gpt-5", "effort": "low", "cwd": "/home/alice/p"}},
            {"timestamp": "2026-01-05T15:00:01.000Z", "type": "response_item",
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": "PRIVATE-SAMPLE-TEXT"}]}}]
    total = usage(0, 0, 0)
    for n, u in enumerate(records):
        total = {k: total[k] + u[k] for k in total}
        ts = "2026-01-05T15:00:%02d.000Z" % (2 + 3 * n)
        rows.append({"timestamp": ts, "type": "token_usage_record", "payload": {
            "thread_id": tid, "session_id": meta["session_id"], "turn_id": "t%d" % n, "root_turn_id": "r0",
            "response_id": "resp_%s_%d" % (tid[:4], n), "usage": u, "turn_token_usage": u,
            "thread_token_usage": total}})
        for _ in range(token_count_repeats):
            rows.append({"timestamp": ts, "type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": total, "last_token_usage": u, "model_context_window": 100000}}})
    d = os.path.join(home, "sessions", "2026", "01", "05")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "rollout-%s-%s.jsonl" % (start, tid)), "w") as f:
        f.write(compact(rows))
    return "2026/01/05/rollout-%s-%s" % (start, tid)


def claude_unpriced(home):
    sid = "aaaaaaaa-0000-4000-8000-000000000001"
    row = {"type": "assistant", "timestamp": "2026-01-05T10:00:00.000Z", "sessionId": sid,
           "cwd": "/home/alice/p", "requestId": "req_x1",
           "message": {"id": "msg_x1", "type": "message", "role": "assistant", "model": "mystery-model-9",
                       "content": [{"type": "text", "text": "PRIVATE-SAMPLE-TEXT"}],
                       "usage": {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0,
                                 "cache_read_input_tokens": 0}}}
    d = os.path.join(home, "projects", "-home-alice-p")
    os.makedirs(d)
    with open(os.path.join(d, sid + ".jsonl"), "w") as f:
        f.write(compact([row]))


def run(*args):
    out = tempfile.mkdtemp()
    r = subprocess.run([sys.executable, "-m", "session_receipt", *args, "--out", out, "--tz", "UTC",
                        "--now", "2026-01-07T12:00:00Z"], cwd=ROOT, capture_output=True, text=True,
                       env=dict(os.environ))
    if r.returncode:
        return r, None, None, None
    get = lambda ext: open(os.path.join(out, next(n for n in os.listdir(out) if n.endswith(ext))), encoding="utf-8").read()
    svg = get(".svg")
    return r, json.loads(get(".json")), " ".join(re.findall(r"<text[^>]*>([^<]*)</text>", svg)), get(".html")


@unittest.skipUnless(CCUSAGE_PRESENT, "needs vendor ccusage")
class F1ClaudeAllUnpriced(unittest.TestCase):
    def test_total_is_unknown_not_zero(self):
        home = tempfile.mkdtemp()
        claude_unpriced(home)
        for args in (["session", "--id", "aaaaaaaa"], ["daily", "--date", "2026-01-05"]):
            r, j, visible, html = run(*args, "--claude-dir", home)
            self.assertEqual(r.returncode, 0, r.stderr)
            t = j["receipts"][0]["totals"]
            self.assertIsNone(t["cost_usd"])
            self.assertTrue(t["partial"])
            self.assertIn("Subtotal (Claude Code) unknown", visible)
            self.assertNotIn("$0.0000", visible + html)


@unittest.skipUnless(CCUSAGE_PRESENT, "needs vendor ccusage")
class F2CodexCountCheck(unittest.TestCase):
    def test_dropped_subagent_is_reported_on_the_daily_receipt(self):
        home = tempfile.mkdtemp()
        rollout(home, PARENT, None, [usage(1000, 0, 10)])
        # the real-log shape ccusage drops: spawned subagent, one response, token_count written twice
        rollout(home, CHILD, PARENT, [usage(15000, 12000, 100)], token_count_repeats=2, start="2026-01-05T15-00-30")
        r, j, visible, _ = run("daily", "--date", "2026-01-05", "--source", "codex", "--codex-home", home)
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = j["receipts"][0]
        self.assertEqual(rec["totals"]["total_tokens"], 1010)      # what ccusage counted
        self.assertEqual(rec["count_check"], {"status": "undercount", "log_tokens": 16110, "missing_tokens": 15100,
                                              "extra_tokens": 0, "skipped_records": 0})
        self.assertTrue(rec["totals"]["partial"])                   # the counts are a lower bound
        self.assertIn("undercount: the Codex logs record 15,100 tokens that ccusage did not count", visible)

    def test_only_usage_of_the_day_dropped_still_gets_a_receipt(self):
        home = tempfile.mkdtemp()
        rollout(home, CHILD, PARENT, [usage(15000, 12000, 100)], token_count_repeats=2)
        r, j, visible, _ = run("daily", "--date", "2026-01-05", "--source", "codex", "--codex-home", home)
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = j["receipts"][0]
        self.assertEqual((rec["source"], rec["totals"]["total_tokens"], rec["totals"]["cost_usd"]), ("codex", 0, None))
        self.assertEqual(rec["count_check"]["missing_tokens"], 15100)
        self.assertIn("undercount: the Codex logs record 15,100 tokens", visible)

    def test_dropped_codex_day_shows_on_a_both_sources_receipt(self):
        home, claude = tempfile.mkdtemp(), tempfile.mkdtemp()
        rollout(home, CHILD, PARENT, [usage(15000, 12000, 100)], token_count_repeats=2)
        claude_unpriced(claude)
        r, j, visible, _ = run("daily", "--date", "2026-01-05", "--source", "both",
                               "--codex-home", home, "--claude-dir", claude)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x["source"] for x in j["receipts"]], ["claude", "codex"])
        self.assertEqual(j["receipts"][1]["count_check"]["status"], "undercount")

    def test_session_id_of_a_dropped_rollout_explains(self):
        home = tempfile.mkdtemp()
        sid = rollout(home, CHILD, PARENT, [usage(15000, 12000, 100)], token_count_repeats=2)
        r, _, _, _ = run("session", "--source", "codex", "--id", sid, "--codex-home", home)
        self.assertEqual(r.returncode, 2)
        self.assertIn("record 15,100 tokens for it, which ccusage did not count", r.stderr)

    def test_partial_drop_in_a_session_receipt(self):
        home = tempfile.mkdtemp()
        sid = rollout(home, CHILD, PARENT, [usage(5000, 0, 100), usage(2000, 0, 300)], token_count_repeats=2)
        r, j, visible, _ = run("session", "--source", "codex", "--id", sid, "--codex-home", home)
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = j["receipts"][0]
        self.assertEqual(rec["count_check"]["status"], "undercount")
        self.assertEqual(rec["count_check"]["log_tokens"], 7400)
        self.assertEqual(rec["count_check"]["missing_tokens"], 7400 - rec["totals"]["total_tokens"])
        self.assertGreater(rec["count_check"]["missing_tokens"], 0)

    def test_matching_counts_are_ok_and_silent(self):
        home = tempfile.mkdtemp()
        sid = rollout(home, PARENT, None, [usage(1000, 400, 10), usage(2000, 1500, 20)])
        r, j, visible, _ = run("session", "--source", "codex", "--id", sid, "--codex-home", home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(j["receipts"][0]["count_check"], {"status": "ok", "log_tokens": 3030, "missing_tokens": 0,
                                                           "extra_tokens": 0, "skipped_records": 0})
        self.assertNotIn("undercount", visible)
        self.assertNotIn("count check", visible)

    def test_malformed_records_never_crash(self):
        home = tempfile.mkdtemp()
        sid = rollout(home, PARENT, None, [usage(1000, 0, 10)])
        path = os.path.join(home, "sessions", sid + ".jsonl")
        bad = ['["token_usage_record"]',
               '{"type":"token_usage_record","timestamp":"2026-01-05T15:00:09Z","payload":{"usage":{"input_tokens":1e999,"output_tokens":1}}}',
               '{"type":"token_usage_record","timestamp":"2026-01-05T15:00:09Z","payload":{"response_id":{},"usage":{"input_tokens":1,"output_tokens":1}}}',
               '{"type":"token_usage_record","timestamp":"2026-01-05T15:00:09Z","payload":{"usage":{"input_tokens":-5,"output_tokens":1}}}',
               '{"type":"token_usage_record","timestamp":"2026-01-05T15:00:09Z","payload":{"usage":{"input_tokens":"1_000","output_tokens":true}}}',
               '{"type":"token_usage_record" not json']
        with open(path, "a") as f:
            f.write("\n".join(bad) + "\n")
        for args in (["session", "--id", sid], ["daily", "--date", "2026-01-05"]):
            r, j, visible, _ = run(*args, "--source", "codex", "--codex-home", home)
            self.assertEqual(r.returncode, 0, r.stderr)
            cc = j["receipts"][0]["count_check"]
            # 5 bad records; the bare JSON list is not a record at all, so it is ignored, not counted
            self.assertEqual((cc["status"], cc["log_tokens"], cc["skipped_records"]), ("incomplete", 1010, 5))
            self.assertIn("count check incomplete: 5 Codex log record(s)", visible)

    def test_ccusage_counting_more_than_the_records_is_a_mismatch(self):
        home = tempfile.mkdtemp()
        sid = rollout(home, PARENT, None, [usage(1000, 0, 10), usage(2000, 0, 20)])
        path = os.path.join(home, "sessions", sid + ".jsonl")
        with open(path) as f:   # keep the token_count events, drop the second response's record
            rows = [x for x in f if '"resp_1111_1"' not in x]
        with open(path, "w") as f:
            f.writelines(rows)
        r, j, visible, _ = run("session", "--id", sid, "--source", "codex", "--codex-home", home)
        self.assertEqual(r.returncode, 0, r.stderr)
        cc = j["receipts"][0]["count_check"]
        self.assertEqual((cc["status"], cc["log_tokens"], cc["extra_tokens"]), ("mismatch", 1010, 2020))
        self.assertIn("ccusage counted 2,020 more tokens", visible)

    def test_timestamps_python_310_cannot_parse(self):
        from session_receipt.codex_check import parse_time
        self.assertEqual(parse_time("2026-01-05T15:00:02.1234Z").microsecond, 123400)
        self.assertEqual(parse_time("2026-01-05T15:00:02.1Z").microsecond, 100000)
        self.assertIsNone(parse_time("2026-13-45T99:00:00Z"))
        self.assertIsNone(parse_time(12345))

    def test_legacy_rollout_without_records_is_not_checked(self):
        from tests.support import fx
        r, j, visible, _ = run("session", "--source", "codex", "--id", "2026/01/05",
                               "--codex-home", fx(os.path.join("g_codex", "codex_home")))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(j["receipts"][0]["count_check"]["status"], "not_checked")
        self.assertNotIn("undercount", visible)


@unittest.skipUnless(CCUSAGE_PRESENT, "needs vendor ccusage")
class F3SubagentWording(unittest.TestCase):
    def test_codex_session_footer_does_not_claim_subagents(self):
        home = tempfile.mkdtemp()
        sid = rollout(home, PARENT, None, [usage(1000, 0, 10)])
        rollout(home, CHILD, PARENT, [usage(2000, 0, 20)], start="2026-01-05T15-00-30")
        r, j, visible, _ = run("session", "--source", "codex", "--id", sid, "--codex-home", home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(j["receipts"][0]["totals"]["total_tokens"], 1010)
        self.assertNotIn("Counts include subagents", visible)
        self.assertIn("Codex subagent threads are separate sessions", visible)

    def test_claude_footer_still_says_subagents_are_included(self):
        from tests.support import fx
        r, j, visible, _ = run("session", "--id", "cccccccc", "--claude-dir", fx("c_subagent"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Claude Code counts include subagents", visible)


if __name__ == "__main__":
    unittest.main()
