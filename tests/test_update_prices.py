"""update-prices: OpenRouter snapshot -> dated reference + overrides, with no network (saved input)."""
import json, os, tempfile, unittest
from unittest import mock

from tests.support import _tmp
from session_receipt import ccusage_adapter as ad, prices, pricecheck

FILES = ("openrouter-snapshot.json", "reference.json", "ccusage-overrides.json")


def openrouter(sonnet_read="0.0000001", haiku_prompt="0.0000001"):
    def m(i, prompt, comp, read, w5, w1h, tiers=None):
        p = {"prompt": prompt, "completion": comp, "input_cache_read": read,
             "input_cache_write": w5, "input_cache_write_1h": w1h, "web_search": "0.01"}
        if tiers:
            p["overrides"] = tiers
        return {"id": i, "pricing": p}
    return json.dumps({"data": [
        m("anthropic/claude-sonnet-5.5", "0.000002", "0.00001", sonnet_read, "0.0000025", "0.000004"),
        m("anthropic/claude-sonnet-5.5:batch", "0.000001", "0.000005", "0.00000005", "0.00000125", "0.000002"),
        m("anthropic/claude-haiku-5.5", haiku_prompt, "0.0000005", "0.00000001", "0.000000125", "0.0000002",
          tiers=[{"min_prompt_tokens": 100000, "prompt": "0.0000005", "completion": "0.0000025"}]),
        {"id": "openai/gpt-5.5", "pricing": {"prompt": "0.000005", "completion": "0.00003"}},
        {"id": "google/gemini-x", "pricing": {"prompt": "1", "completion": "1"}},
    ]}).encode()


class TestUpdatePrices(unittest.TestCase):
    def run_update(self, raw):
        d = tempfile.mkdtemp(dir=_tmp)
        ref, ovr, notes = prices.update(raw, "2026-10-21T20:58:00Z", pricing_dir=d, log=lambda *_: None)
        return d, ref, ovr, notes

    def test_agreeing_snapshot_needs_no_overrides(self):
        d, ref, ovr, notes = self.run_update(openrouter())
        self.assertEqual(ovr, {})
        self.assertEqual(sorted(ref["models"]), ["haiku-5-5", "sonnet-5-5"])  # no :batch, no gemini
        self.assertEqual(ref["as_of"], "2026-10-21")
        self.assertEqual(ref["source"], "OpenRouter list")
        self.assertAlmostEqual(ref["models"]["sonnet-5-5"]["cache_read"], 0.10, places=9)
        with open(os.path.join(d, "openrouter-snapshot.json")) as f:
            snap = json.load(f)
        self.assertIn("openai/gpt-5.5", snap["models"])
        self.assertNotIn("google/gemini-x", snap["models"])

    def test_disagreement_becomes_override_that_ccusage_applies(self):
        d, ref, ovr, notes = self.run_update(openrouter(sonnet_read="0.0000002"))
        self.assertEqual(list(ovr), ["claude-sonnet-5-5"])
        self.assertAlmostEqual(ovr["claude-sonnet-5-5"]["cacheReadInputTokenCost"], 2e-7)
        res = pricecheck.check_model("claude-sonnet-5-5", os.path.join(d, "ccusage-overrides.json"),
                                     use_cache=False, reference_path=os.path.join(d, "reference.json"))
        self.assertEqual(res["status"], "ok")
        self.assertAlmostEqual(res["effective"]["cache_read"], 0.20, places=9)

    def test_tiered_model_is_never_flattened(self):
        d, ref, ovr, notes = self.run_update(openrouter(haiku_prompt="0.0000002"))
        self.assertNotIn("claude-haiku-5-5", ovr)
        self.assertTrue(any("haiku-5-5" in n and "NOT overridden" in n for n in notes))
        self.assertEqual(ref["models"]["haiku-5-5"]["tiers"][0]["min_prompt_tokens"], 100000)


class TestUpdateFailureKeepsOldFiles(unittest.TestCase):
    """A failed update must leave the active pricing files exactly as they were."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=_tmp)
        prices.update(openrouter(), "2026-10-01T00:00:00Z", pricing_dir=self.dir, log=lambda *_: None)
        self.before = self.snapshot_files()
        self.new = openrouter(sonnet_read="0.0000002")  # valid, and changes every file

    def snapshot_files(self):
        out = {}
        for n in FILES:
            with open(os.path.join(self.dir, n), "rb") as f:
                out[n] = f.read()
        return out

    def update(self, raw=None):
        return prices.update(self.new if raw is None else raw, "2026-10-21T20:58:00Z",
                             pricing_dir=self.dir, log=lambda *_: None)

    def assert_unchanged(self):
        self.assertEqual(self.snapshot_files(), self.before)
        self.assertEqual(sorted(os.listdir(self.dir)), sorted(FILES))  # no staging left behind

    def test_probe_failure_after_a_successful_probe(self):
        real, calls = pricecheck.check_model, []

        def second_probe_fails(*a, **kw):
            calls.append(a[0])
            if len(calls) == 2:
                raise ad.ReceiptError("ccusage failed (exit 1): boom")
            return real(*a, **kw)

        with mock.patch.object(pricecheck, "check_model", side_effect=second_probe_fails):
            with self.assertRaisesRegex(ad.ReceiptError, "boom"):
                self.update()
        self.assertEqual(calls, ["claude-haiku-5-5", "claude-sonnet-5-5"])  # the first one ran
        self.assert_unchanged()

    def test_missing_ccusage(self):
        with mock.patch.dict(os.environ, {"SESSION_RECEIPT_CCUSAGE": os.path.join(self.dir, "nope")}):
            with self.assertRaisesRegex(ad.ReceiptError, "ccusage binary not found"):
                self.update()
        self.assert_unchanged()

    def test_unusable_probe_output(self):
        real = ad.run_ccusage

        def no_sessions(args, **kw):
            return real(args, **kw) if args == ["--version"] else {"sessions": []}

        with mock.patch.object(ad, "run_ccusage", side_effect=no_sessions):
            with self.assertRaisesRegex(ad.ReceiptError, "returned 0 sessions"):
                self.update()
        self.assert_unchanged()

    def test_parse_errors(self):
        bad = [b"not json", b"[]", b'{"models": []}', b'{"data": "x"}',
               json.dumps({"data": [{"id": "anthropic/claude-x", "pricing": {"prompt": "abc"}}]}).encode(),
               json.dumps({"data": [{"id": "anthropic/claude-x", "pricing": []}]}).encode()]
        for raw in bad:
            with self.subTest(raw=raw[:40]):
                with self.assertRaisesRegex(ad.ReceiptError, "OpenRouter response"):
                    self.update(raw)
                self.assert_unchanged()

    def test_no_claude_prices(self):
        with self.assertRaisesRegex(ad.ReceiptError, "no Claude prices"):
            self.update(json.dumps({"data": [{"id": "openai/gpt-5.5", "pricing": {}}]}).encode())
        self.assert_unchanged()

    def replace_failing_at(self, name, also_fail=()):
        """os.replace that raises when publishing `name`, and on any rollback onto `also_fail`."""
        real, published = os.replace, []

        def fake(src, dst):
            base = os.path.basename(dst)
            if os.path.dirname(os.path.abspath(dst)) == os.path.abspath(self.dir):
                if base == name and base not in published or base in also_fail and base in published:
                    raise OSError("simulated failure replacing " + base)
                published.append(base)
            return real(src, dst)
        return mock.patch.object(prices.os, "replace", side_effect=fake)

    def test_publish_failure_rolls_back_files_already_replaced(self):
        for name in FILES[1:]:  # at least one file is already replaced when this one fails
            with self.subTest(failing=name):
                with self.replace_failing_at(name):
                    with self.assertRaisesRegex(ad.ReceiptError, "previous pricing files restored"):
                        self.update()
                self.assert_unchanged()

    def test_publish_failure_on_first_use_removes_new_files(self):
        self.dir = tempfile.mkdtemp(dir=_tmp)
        with self.replace_failing_at("ccusage-overrides.json"):
            with self.assertRaises(ad.ReceiptError):
                self.update()
        self.assertEqual(os.listdir(self.dir), [])

    def test_backup_failure_changes_nothing(self):
        with mock.patch.object(prices.shutil, "copyfile", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(ad.ReceiptError, "nothing changed"):
                self.update()
        self.assert_unchanged()

    def test_failed_rollback_says_where_the_old_files_are(self):
        with self.replace_failing_at("ccusage-overrides.json", also_fail=("reference.json",)):
            with self.assertRaisesRegex(ad.ReceiptError, "could not restore") as e:
                self.update()
        msg = str(e.exception)
        self.assertIn("reference.json", msg)
        kept = [n for n in os.listdir(self.dir) if n not in FILES]
        self.assertEqual(len(kept), 1)
        self.assertIn(kept[0], msg)
        with open(os.path.join(self.dir, kept[0], "previous", "reference.json"), "rb") as f:
            self.assertEqual(f.read(), self.before["reference.json"])  # recoverable by hand

    def test_success_replaces_all_three_consistently(self):
        ref, ovr, notes = self.update()
        after = self.snapshot_files()
        self.assertTrue(all(after[n] != self.before[n] for n in FILES))
        self.assertEqual(sorted(os.listdir(self.dir)), sorted(FILES))
        snap = json.loads(after["openrouter-snapshot.json"])
        on_disk = json.loads(after["reference.json"])
        self.assertEqual(on_disk, ref)
        self.assertEqual(snap["sha256"], ref["sha256"])
        self.assertEqual(snap["fetched_at"], "2026-10-21T20:58:00Z")
        self.assertEqual(json.loads(after["ccusage-overrides.json"]),
                         {"defaults": {"pricingOverrides": ovr}})
        self.assertEqual(list(ovr), ["claude-sonnet-5-5"])
        res = pricecheck.check_model("claude-sonnet-5-5", os.path.join(self.dir, "ccusage-overrides.json"),
                                     use_cache=False, reference_path=os.path.join(self.dir, "reference.json"))
        self.assertEqual(res["status"], "ok")


if __name__ == "__main__":
    unittest.main()
