import re
import json
import os
import tempfile
import unittest
from unittest import mock

from tests.support import cli, _tmp
from session_receipt import pricecheck, ccusage_adapter as ad, render_svg


def empty_config():
    p = os.path.join(tempfile.mkdtemp(dir=_tmp), "empty.json")
    with open(p, "w") as f:
        f.write("{}")
    return p


def wrong_reference():
    """The shipped reference with sonnet-5-5 cache_read set to $0.20 (the stale doc figure;
    Anthropic's pricing page and OpenRouter both say $0.10 = 0.05x input)."""
    ref = pricecheck.load_reference()
    ref["models"]["sonnet-5-5"]["cache_read"] = 0.20
    p = os.path.join(tempfile.mkdtemp(dir=_tmp), "reference.json")
    with open(p, "w") as f:
        json.dump(ref, f)
    return p


class TestPriceCheck(unittest.TestCase):
    def test_sonnet_matches_snapshot_without_overrides(self):
        r = pricecheck.check_model("claude-sonnet-5-5", empty_config(), use_cache=False)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["effective"]["cache_read"], 0.10, places=9)

    def test_wrong_reference_is_detected(self):
        r = pricecheck.check_model("claude-sonnet-5-5", empty_config(), use_cache=False,
                                   reference_path=wrong_reference())
        self.assertEqual(r["status"], "mismatch")
        self.assertEqual(r["differing"], ["cache_read"])
        self.assertAlmostEqual(r["effective"]["cache_read"], 0.10, places=9)
        self.assertAlmostEqual(r["reference"]["cache_read"], 0.20, places=9)

    def test_haiku_ok_deviation_from_spec(self):
        # SPEC expected a haiku-5-5 mismatch.  Measured: it only appears with a 1M-token probe,
        # which crosses haiku's >100K-prompt tier.  Below the tier ccusage matches the list price.
        self.assertEqual(pricecheck.check_model("claude-haiku-5-5", use_cache=False)["status"], "ok")

    def test_haiku_tier_is_priced_by_ccusage_above_100k(self):
        # One haiku message with 150,000 input tokens: tier rate $0.50/MTok on all of it
        # -> 150000 * 0.50 = 75000 micro-USD = $0.075 (the standard rate would give $0.015).
        rec = pricecheck._probe_record("claude-haiku-5-5", "input")
        rec["message"]["usage"]["input_tokens"] = 150000
        with tempfile.TemporaryDirectory(dir=_tmp) as t:
            d = os.path.join(t, "projects", "x")
            os.makedirs(d)
            with open(os.path.join(d, "a.jsonl"), "w") as f:
                f.write(json.dumps(rec, separators=(",", ":")) + "\n")
            data = ad.run_ccusage(["claude", "session", "--json", "--offline", "-z", "UTC",
                                   "--config", ad.OVERRIDES], claude_dir=t)
        self.assertAlmostEqual(data["sessions"][0]["totalCost"], 0.075, places=9)

    def test_fake_model_is_unverified(self):
        self.assertEqual(pricecheck.check_model("claude-totally-fake-9")["status"], "unverified")
        rc, out, err = cli("pricecheck", "--model", "claude-totally-fake-9")
        self.assertEqual(rc, 0)
        self.assertIn("unverified", out)

    def test_all_reference_models_ok_via_cli(self):
        rc, out, err = cli("pricecheck")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(out.count(" ok"), len(pricecheck.load_reference()["models"]))

    def test_mismatch_is_flagged_on_the_receipt(self):
        from tests.support import fx
        cfg = empty_config()
        with mock.patch.object(pricecheck, "REFERENCE", wrong_reference()):
            rs = ad.fetch_claude_sessions("UTC", claude_dir=fx("a_simple"), config=cfg)
            for r in rs:
                pricecheck.apply_to_receipt(r, cfg, use_cache=False)
                ad.mark_provisional(r, ad.parse_now("2026-01-06T12:00:00Z"))
            svg = render_svg.render_svg(rs, "2026-01-06T12:00:00Z")
        # ccusage charges sonnet cache read at 0.10: 110*2 + 450*10 + 1000*2.5
        # + 2500*0.10 = 220 + 4500 + 2500 + 250 = 7470 micro-USD -> "$0.0075"
        self.assertIn("$0.0075 ⚠1", svg)
        # (footnote text is word-wrapped across SVG lines, so check the fragments)
        # compare visible text: footnotes wrap across <text> lines at length-dependent points
        visible = " ".join(re.findall(r"<text[^>]*>([^<]*)</text>", svg))
        self.assertIn("price mismatch: cache_read: ccusage charges $0.10/MTok, OpenRouter list is $0.20/MTok", visible)


if __name__ == "__main__":
    unittest.main()
