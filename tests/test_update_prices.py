"""update-prices: OpenRouter snapshot -> dated reference + overrides, with no network (saved input)."""
import json, os, tempfile, unittest

from tests.support import _tmp
from session_receipt import prices, pricecheck


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


if __name__ == "__main__":
    unittest.main()
