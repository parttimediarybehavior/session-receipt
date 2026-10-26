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
        self.assertIn("npm ci --prefix", se)
        self.assertIn("session-receipt doctor", se)

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


class TestDefaultTz(unittest.TestCase):
    """The --tz default; files are passed in so the real /etc is never read."""

    def setUp(self):
        self.d = tempfile.mkdtemp(dir=_tmp)
        self.none = os.path.join(self.d, "missing")

    def tz(self, environ=None, timezone_file=None, localtime=None):
        from session_receipt.cli import default_tz
        return default_tz(environ or {}, timezone_file or self.none, localtime or self.none)

    def link(self, target):
        path = os.path.join(self.d, "localtime")
        try:
            os.symlink(target, path)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create symlinks here")
        return path

    def test_nothing_set_is_utc(self):
        self.assertEqual(self.tz(), "UTC")

    def test_session_receipt_tz_wins_over_tz_and_etc_timezone(self):  # no symlink: runs on Windows
        f = os.path.join(self.d, "timezone")
        with open(f, "w") as fh:
            fh.write("Europe/Berlin\n")
        self.assertEqual(self.tz({"SESSION_RECEIPT_TZ": "Asia/Tokyo", "TZ": "Europe/Paris"}, timezone_file=f),
                         "Asia/Tokyo")
        self.assertEqual(self.tz({"SESSION_RECEIPT_TZ": "", "TZ": "Europe/Paris"}, timezone_file=f),
                         "Europe/Paris")  # empty counts as unset

    def test_variables_win_over_localtime(self):
        link = self.link("/usr/share/zoneinfo/America/Chicago")
        self.assertEqual(self.tz({"SESSION_RECEIPT_TZ": "Asia/Tokyo"}, localtime=link), "Asia/Tokyo")
        self.assertEqual(self.tz({"TZ": "Europe/Paris"}, localtime=link), "Europe/Paris")

    def test_tz_then_etc_timezone(self):
        f = os.path.join(self.d, "timezone")
        with open(f, "w") as fh:
            fh.write("Europe/Berlin\n")
        self.assertEqual(self.tz({"TZ": "Europe/Paris"}, timezone_file=f), "Europe/Paris")
        self.assertEqual(self.tz(timezone_file=f), "Europe/Berlin")

    def test_localtime_symlink(self):
        for target, want in (("/usr/share/zoneinfo/America/Chicago", "America/Chicago"),     # Fedora, Arch
                             ("/var/db/timezone/zoneinfo/Europe/London", "Europe/London"),   # macOS
                             ("../usr/share/zoneinfo/posix/Asia/Kolkata", "Asia/Kolkata")):
            with self.subTest(target=target):
                self.assertEqual(self.tz(localtime=self.link(target)), want)
                os.remove(os.path.join(self.d, "localtime"))

    def test_unusable_localtime_is_utc(self):
        for target in ("/usr/share/zoneinfo/Not/AZone", "/usr/share/zoneinfo/", "/etc/some-copy"):
            with self.subTest(target=target):
                self.assertEqual(self.tz(localtime=self.link(target)), "UTC")
                os.remove(os.path.join(self.d, "localtime"))

    def test_copied_localtime_is_utc(self):  # a plain file, not a symlink
        f = os.path.join(self.d, "plain")
        open(f, "w").close()
        self.assertEqual(self.tz(localtime=f), "UTC")

    def test_unknown_zone_names_its_source(self):
        from unittest import mock
        from session_receipt.cli import _tz, ReceiptError
        with mock.patch.dict(os.environ, {"SESSION_RECEIPT_TZ": "Central Standard Time"}):
            with self.assertRaises(ReceiptError) as e:
                _tz("Central Standard Time")
        self.assertIn("'Central Standard Time' (from SESSION_RECEIPT_TZ)", str(e.exception))
        self.assertIn("use an IANA name such as America/Chicago", str(e.exception))
        with mock.patch.dict(os.environ, {"SESSION_RECEIPT_TZ": "", "TZ": ""}):
            with self.assertRaises(ReceiptError) as e:
                _tz("Not/AZone")  # from --tz: no source named
        self.assertNotIn("(from", str(e.exception))

    def test_windows_without_tzdata_points_at_doctor(self):
        from types import SimpleNamespace as NS
        from unittest import mock
        from session_receipt import cli
        for spec, want in ((None, True), (object(), False)):
            with self.subTest(tzdata_installed=spec is not None), \
                    mock.patch.object(cli, "os", NS(name="nt", environ={})), \
                    mock.patch.object(cli, "importlib", NS(util=NS(find_spec=lambda name, s=spec: s))):
                with self.assertRaises(cli.ReceiptError) as e:
                    cli._tz("Not/AZone")
            msg = str(e.exception)
            self.assertEqual("install tzdata (session-receipt doctor prints the command)" in msg, want, msg)
            self.assertIn("use an IANA name such as America/Chicago", msg)
