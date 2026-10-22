"""Hand-counted expectations.  Every number is a literal derived by reasoning from
examples/make_fixtures.py; no parser is called to produce an expected value.

Prices used (USD per MTok, Anthropic list; ccusage with our overrides):
  sonnet-5-5: in 2, out 10, cache write 2.5, cache read 0.10 (0.05x input; Anthropic pricing page + OpenRouter, 2026-10-21)
  haiku-5-5 : in 0.10, out 0.50, cache write 0.125, cache read 0.01
"""
import unittest

from tests.support import cli_json, fx

SID_A = "aaaaaaaa-1111-4111-8111-000000000001"
SID_B1 = "bbbbbbbb-1111-4111-8111-000000000001"
SID_B2 = "bbbbbbbb-2222-4222-8222-000000000002"
SID_C = "cccccccc-1111-4111-8111-000000000001"


def models(doc, i=0):
    return {m["name"]: m for m in doc["receipts"][i]["models"]}


def sess(fixture, sid, *extra):
    return cli_json("session", "--id", sid, "--tz", "UTC", "--claude-dir", fx(fixture),
                    "--now", "2026-01-06T12:00:00Z", *extra)


class TestFixtureA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = sess("a_simple", SID_A)
        cls.r = cls.doc["receipts"][0]
        cls.m = models(cls.doc)

    def test_sonnet_tokens_dup_keeps_larger_output_first_record(self):
        s = self.m["claude-sonnet-5-5"]
        # input: a1 100 + a2 (kept first record) 10 = 110. The later dup (input 12) is dropped.
        self.assertEqual(s["input"], 110)
        # output: a1 50 + a2 larger-first 400 = 450 (later dup output 20 dropped)
        self.assertEqual(s["output"], 450)
        self.assertEqual(s["cache_write"], 1000)   # only a1
        # cache read: a1 2000 + a2 kept 500 = 2500 (dropped dup had 600)
        self.assertEqual(s["cache_read"], 2500)

    def test_sonnet_cost(self):
        # 110*2 = 220; 450*10 = 4500; 1000*2.5 = 2500; 2500*0.1 = 250 -> 7470 micro-USD
        self.assertAlmostEqual(self.m["claude-sonnet-5-5"]["cost_usd"], 0.00747, places=9)

    def test_haiku(self):
        h = self.m["claude-haiku-5-5"]
        self.assertEqual((h["input"], h["output"], h["cache_write"], h["cache_read"]), (1000, 200, 0, 0))
        # 1000*0.10 = 100; 200*0.50 = 100 -> 200 micro-USD
        self.assertAlmostEqual(h["cost_usd"], 0.0002, places=9)

    def test_unknown_model_has_tokens_but_no_cost(self):
        u = self.m["mystery-model-9"]
        self.assertEqual((u["input"], u["output"]), (300, 30))
        self.assertIsNone(u["cost_usd"])
        self.assertEqual(self.r["unpriced"], ["mystery-model-9"])

    def test_totals_malformed_line_skipped(self):
        t = self.r["totals"]
        # input 110+1000+300 = 1410; output 450+200+30 = 680; cw 1000; cr 2500
        self.assertEqual((t["input"], t["output"], t["cache_write"], t["cache_read"]), (1410, 680, 1000, 2500))
        self.assertEqual(t["total_tokens"], 5590)   # 1410+680+1000+2500
        # priced models only: 0.00747 + 0.0002 = 0.00767
        self.assertAlmostEqual(t["cost_usd"], 0.00767, places=9)
        self.assertTrue(t["partial"])


class TestFixtureB(unittest.TestCase):
    def test_sessions_not_mixed(self):
        b1 = models(sess("b_concurrent", SID_B1))["claude-sonnet-5-5"]
        b2 = models(sess("b_concurrent", SID_B2))["claude-sonnet-5-5"]
        # B1: input 100+200 = 300, output 10+20 = 30; cost 300*2 + 30*10 = 900 micro-USD
        self.assertEqual((b1["input"], b1["output"]), (300, 30))
        self.assertAlmostEqual(b1["cost_usd"], 0.0009, places=9)
        # B2: input 1000+2000 = 3000, output 100+200 = 300; cost 6000 + 3000 = 9000 micro-USD
        self.assertEqual((b2["input"], b2["output"]), (3000, 300))
        self.assertAlmostEqual(b2["cost_usd"], 0.009, places=9)

    def test_latest_is_the_later_lastActivity(self):
        # B2 last activity 09:30 beats B1's 09:20 -> latest = B2 (input 3000)
        doc = cli_json("session", "--latest", "--tz", "UTC", "--claude-dir", fx("b_concurrent"),
                       "--now", "2026-01-06T12:00:00Z")
        self.assertEqual(models(doc)["claude-sonnet-5-5"]["input"], 3000)


class TestFixtureC(unittest.TestCase):
    def test_subagent_included_in_parent(self):
        doc = sess("c_subagent", SID_C)
        self.assertEqual(len(doc["receipts"]), 1)
        m = models(doc)
        s, h = m["claude-sonnet-5-5"], m["claude-haiku-5-5"]
        self.assertEqual((s["input"], s["output"], s["cache_read"]), (100, 10, 1000))
        # sonnet: 100*2 = 200; 10*10 = 100; 1000*0.1 = 100 -> 400 micro-USD
        self.assertAlmostEqual(s["cost_usd"], 0.0004, places=9)
        # subagent (haiku): in 50, out 5, cache read 400
        self.assertEqual((h["input"], h["output"], h["cache_read"]), (50, 5, 400))
        # haiku: 50*0.1 = 5; 5*0.5 = 2.5; 400*0.01 = 4 -> 11.5 micro-USD
        self.assertAlmostEqual(h["cost_usd"], 0.0000115, places=10)
        t = doc["receipts"][0]["totals"]
        self.assertEqual(t["total_tokens"], 1565)   # 150 in + 15 out + 1400 cache read


class TestFixtureD(unittest.TestCase):
    def daily(self, date, tz):
        return cli_json("daily", "--date", date, "--tz", tz, "--claude-dir", fx("d_tz_boundary"),
                        "--now", "2026-01-10T12:00:00Z")

    def test_new_york_two_days(self):
        # 04:30Z = 23:30 on 01-04 in New York (UTC-5); 05:30Z = 00:30 on 01-05
        d4 = self.daily("2026-01-04", "America/New_York")["receipts"][0]
        d5 = self.daily("2026-01-05", "America/New_York")["receipts"][0]
        self.assertEqual((d4["totals"]["input"], d4["totals"]["output"]), (100, 10))
        self.assertEqual((d5["totals"]["input"], d5["totals"]["output"]), (200, 20))
        self.assertAlmostEqual(d4["totals"]["cost_usd"], 0.0003, places=9)   # 100*2 + 10*10 = 300 micro-USD
        self.assertAlmostEqual(d5["totals"]["cost_usd"], 0.0006, places=9)   # 200*2 + 20*10 = 600 micro-USD
        self.assertEqual(d4["label"], "one day, 2026-01-04, America/New_York")

    def test_utc_one_day(self):
        d = self.daily("2026-01-05", "UTC")["receipts"][0]
        self.assertEqual((d["totals"]["input"], d["totals"]["output"]), (300, 30))   # 100+200, 10+20
        self.assertAlmostEqual(d["totals"]["cost_usd"], 0.0009, places=9)            # 600 + 300 micro-USD

    def test_utc_has_no_jan_4(self):
        from tests.support import cli
        rc, _, err = cli("daily", "--date", "2026-01-04", "--tz", "UTC", "--claude-dir", fx("d_tz_boundary"))
        self.assertEqual(rc, 2)
        self.assertIn("no usage recorded", err)


class TestCodex(unittest.TestCase):
    def test_codex_fixture(self):
        doc = cli_json("session", "--source", "codex", "--latest", "--tz", "UTC",
                       "--codex-home", fx("g_codex/codex_home"), "--now", "2026-01-06T12:00:00Z")
        r = doc["receipts"][0]
        m = r["models"][0]
        self.assertEqual(m["name"], "gpt-5")
        # fresh input = (1000-400) + (2000-1500) = 1100; cache read 400+1500 = 1900; output 100+300 = 400
        self.assertEqual((m["input"], m["cache_read"], m["output"]), (1100, 1900, 400))
        self.assertEqual(m["reasoning"], 130)      # 30+100, subset of output, never added
        self.assertEqual(r["totals"]["total_tokens"], 3400)   # 1100 + 1900 + 400
        # ccusage gpt-5 table: $1.25 in, $0.125 cached, $10 out per MTok:
        # 1100*1.25 = 1375; 1900*0.125 = 237.5; 400*10 = 4000 -> 5612.5 micro-USD
        self.assertAlmostEqual(r["totals"]["cost_usd"], 0.0056125, places=9)
        self.assertEqual(m["price_check"], "unverified")


class TestEnvironment(unittest.TestCase):
    def test_env_scenarios_fixture_a(self):
        doc = sess("a_simple", SID_A, "--env")
        lv = doc["receipts"][0]["environmental_scenarios"]["levels"]
        # tokens: out 680, fresh in+cache write 1410+1000 = 2410, cache read 2500 (mWh per token):
        # CENTRAL 680*1.0 + 2410*0.10 + 2500*0.01 = 680 + 241 + 25 = 946 mWh = 0.000946 kWh
        self.assertAlmostEqual(lv["central"]["kwh"], 0.000946, places=12)
        # LOW 680*0.2 + 2410*0.03 + 2500*0.003 = 136 + 72.3 + 7.5 = 215.8 mWh
        self.assertAlmostEqual(lv["low"]["kwh"], 0.0002158, places=12)
        # HIGH 680*3.2 + 2410*0.25 + 2500*0.25 = 2176 + 602.5 + 625 = 3403.5 mWh
        self.assertAlmostEqual(lv["high"]["kwh"], 0.0034035, places=12)
        # CO2e: central 0.000946*0.287 = 0.000271502 kg ; high 0.0034035*0.5 = 0.00170175 kg
        self.assertAlmostEqual(lv["central"]["kg_co2e"], 0.000271502, places=12)
        self.assertAlmostEqual(lv["high"]["kg_co2e"], 0.00170175, places=12)
        # water high 0.0034035*5.3 = 0.01803855 L
        self.assertAlmostEqual(lv["high"]["litres"], 0.01803855, places=12)

    def test_env_absent_by_default(self):
        doc = sess("a_simple", SID_A)
        self.assertNotIn("environmental_scenarios", doc["receipts"][0])


if __name__ == "__main__":
    unittest.main()
