import os
import tempfile
import unittest

from tests.support import read, cli, fx, _tmp, ROOT


class TestCli(unittest.TestCase):
    def test_demo(self):
        out = tempfile.mkdtemp(dir=_tmp)
        rc, so, se = cli("demo", "--out", out, "--now", "2026-01-06T12:00:00Z")
        self.assertEqual(rc, 0, se)
        names = os.listdir(out)
        for n in ("demo-simple.html", "demo-simple.svg", "demo-simple.json", "demo-hostile.html"):
            self.assertIn(n, names)
        self.assertEqual(len(so.split()), len(names))
        svg = read(os.path.join(out, "demo-simple.svg"))
        self.assertIn('width="600"', svg)
        self.assertIn("CLAUDE CODE", svg)
        self.assertIn("CODEX", svg)
        self.assertIn("Illustrative scenarios, not measurements", svg)
        self.assertIn("API list-price equivalent. Not what a subscription plan bills.", svg)
        self.assertNotIn("PROVISIONAL", svg)

    def test_missing_session_id(self):
        rc, so, se = cli("session", "--id", "deadbeef-nope", "--tz", "UTC", "--claude-dir", fx("a_simple"),
                         "--out", tempfile.mkdtemp(dir=_tmp))
        self.assertNotEqual(rc, 0)
        self.assertIn("not found", se)

    def test_empty_fixture(self):
        rc, so, se = cli("session", "--latest", "--tz", "UTC", "--claude-dir", fx("e_empty"),
                         "--since", "2026-01-01", "--until", "2026-01-31", "--out", tempfile.mkdtemp(dir=_tmp))
        self.assertEqual(rc, 2)
        self.assertIn("no sessions found", se)
        rc, so, se = cli("daily", "--date", "2026-01-05", "--tz", "UTC", "--claude-dir", fx("e_empty"))
        self.assertEqual(rc, 2)
        self.assertIn("no usage recorded", se)

    def test_missing_ccusage_binary(self):
        rc, so, se = cli("session", "--latest", "--claude-dir", fx("a_simple"),
                         env={"SESSION_RECEIPT_CCUSAGE": "/nonexistent/ccusage"})
        self.assertEqual(rc, 1)
        self.assertIn("ccusage binary not found", se)
        self.assertIn("npm ci --prefix vendor", se)

    def test_bad_claude_dir_is_a_clear_error(self):
        rc, so, se = cli("session", "--latest", "--claude-dir", "/nonexistent/dir")
        self.assertEqual(rc, 1)
        self.assertIn("ccusage failed", se)

    def test_provisional_flag(self):
        base = ["session", "--id", "aaaaaaaa", "--tz", "UTC", "--claude-dir", fx("a_simple"), "--format", "svg"]
        # last activity 10:03:00Z.  now = 10:04:30Z is 90 s later -> provisional
        out = tempfile.mkdtemp(dir=_tmp)
        self.assertEqual(cli(*base, "--out", out, "--now", "2026-01-05T10:04:30Z")[0], 0)
        self.assertIn("PROVISIONAL: session may still be running; later usage not included.",
                      read(os.path.join(out, os.listdir(out)[0])))
        # next day, > 2 min -> not provisional
        out = tempfile.mkdtemp(dir=_tmp)
        self.assertEqual(cli(*base, "--out", out, "--now", "2026-01-06T10:04:30Z")[0], 0)
        self.assertNotIn("PROVISIONAL", read(os.path.join(out, os.listdir(out)[0])))
        # same day but 5 h later: window includes today -> still provisional
        out = tempfile.mkdtemp(dir=_tmp)
        self.assertEqual(cli(*base, "--out", out, "--now", "2026-01-05T15:03:00Z")[0], 0)
        self.assertIn("PROVISIONAL", read(os.path.join(out, os.listdir(out)[0])))

    def test_no_model_or_network_imports(self):
        import re
        banned = re.compile(r"^\s*(import|from)\s+(urllib|http|socket|requests|anthropic|openai)\b", re.M)
        pkg = os.path.join(ROOT, "session_receipt")
        for n in os.listdir(pkg):
            # prices.py is the one deliberate exception: `update-prices` downloads the price list
            # when the user runs it. Its network import is local to fetch(); receipts never call it.
            if n.endswith(".py") and n != "prices.py":
                self.assertIsNone(banned.search(read(os.path.join(pkg, n))), n)

    def test_receipts_never_fetch_prices(self):
        import contextlib, io, socket, urllib.request
        from unittest import mock
        from session_receipt import cli as sr_cli
        boom = AssertionError("network used")
        with mock.patch.object(urllib.request, "urlopen", side_effect=boom), \
             mock.patch.object(socket, "create_connection", side_effect=boom), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sr_cli.main(["demo", "--out", tempfile.mkdtemp(dir=_tmp)]), 0)


if __name__ == "__main__":
    unittest.main()
