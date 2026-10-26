"""bin/ launchers and `doctor`: run the CLI from a checkout or plugin with no pip install."""
import io
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock
from zoneinfo import ZoneInfoNotFoundError

from session_receipt import cli

from tests.support import ROOT, CCUSAGE_PRESENT, _tmp

SH = shutil.which("sh") or next((p for p in (r"C:\Program Files\Git\bin\sh.exe",) if os.path.exists(p)), None)
NOW = "2026-01-06T12:00:00Z"


class Launchers(unittest.TestCase):
    def setUp(self):
        # Another folder, holding a json.py that would break the CLI if the folder came first on sys.path.
        self.cwd = tempfile.mkdtemp(dir=_tmp)
        with open(os.path.join(self.cwd, "json.py"), "w") as f:
            f.write("raise SystemExit('shadowed by the working directory')\n")

    def check_demo(self, argv):
        r = subprocess.run(argv + ["demo", "--out", "demo", "--now", NOW], cwd=self.cwd,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.cwd, "demo", "demo-simple.svg")))  # relative to cwd

    @unittest.skipUnless(SH, "needs sh (Git Bash on Windows)")
    def test_sh_launcher(self):
        self.check_demo([SH, os.path.join(ROOT, "bin", "session-receipt")])

    @unittest.skipUnless(os.name == "nt", "Windows cmd")
    def test_cmd_launcher(self):
        self.check_demo(["cmd", "/c", os.path.join(ROOT, "bin", "session-receipt.cmd")])

    @unittest.skipUnless(SH, "needs sh (Git Bash on Windows)")
    def test_sh_launcher_without_python_says_so(self):
        empty = tempfile.mkdtemp(dir=_tmp)
        env = {k: v for k, v in os.environ.items() if k in ("SYSTEMROOT", "TEMP", "TMP")}
        env["PATH"] = empty
        r = subprocess.run([SH, os.path.join(ROOT, "bin", "session-receipt"), "doctor"], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("needs Python 3.10 or later", r.stderr)


class Doctor(unittest.TestCase):
    def run_doctor(self, env):
        e = dict(os.environ)
        e.update(env)
        return subprocess.run([sys.executable, "-m", "session_receipt", "doctor"], cwd=ROOT, env=e,
                              capture_output=True, text=True, timeout=60)

    def test_missing_ccusage_names_the_fix(self):
        r = self.run_doctor({"SESSION_RECEIPT_CCUSAGE": os.path.join(_tmp, "no-such-ccusage")})
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertRegex(r.stdout, r"MISSING +ccusage +SESSION_RECEIPT_CCUSAGE is .*Fix the path or unset it")

    @unittest.skipUnless(CCUSAGE_PRESENT, "needs ccusage (npm ci)")
    def test_all_present(self):
        r = self.run_doctor({"SESSION_RECEIPT_CCUSAGE": ""})
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertRegex(r.stdout, r"ok +ccusage +ccusage 20\.0\.38")
        self.assertNotIn("MISSING", r.stdout)


class MissingTimeZones(unittest.TestCase):
    WIN = r"C:\Users\Jane Doe\AppData\Local\Programs\Python\Python313\python.exe"

    def test_doctor_reports_it_with_the_fix(self):
        out = io.StringIO()
        with mock.patch.object(cli, "ZoneInfo", side_effect=ZoneInfoNotFoundError("none")), \
                redirect_stdout(out):
            rc = cli.cmd_doctor(None)
        self.assertEqual(rc, 1)
        line = next(l for l in out.getvalue().splitlines() if "time zones" in l)
        self.assertRegex(line, r"^MISSING +time zones +no IANA time zone database\. ")
        self.assertTrue(line.endswith(cli.tzdata_install()), line)

    def test_windows_command_is_for_powershell(self):
        fix = cli.tzdata_install(self.WIN, nt=True, venv=False)
        self.assertEqual(fix, 'In PowerShell, run: & "%s" -m pip install --user tzdata' % self.WIN)

    def test_windows_path_with_dollar_stays_literal(self):
        fix = cli.tzdata_install(r"C:\Users\a$b\python.exe", nt=True, venv=False)
        self.assertIn(r'& "C:\Users\a`$b\python.exe" -m pip', fix)

    def test_unix_command_is_for_sh(self):
        py = "/home/jane doe/.pyenv/versions/3.12.0/bin/python3"
        fix = cli.tzdata_install(py, nt=False, venv=False)
        self.assertEqual(fix, "In a terminal, run: '%s' -m pip install --user tzdata" % py)
        self.assertNotIn("&", fix)
        self.assertEqual(shlex.split(fix.split(": ", 1)[1])[0], py)

    def test_venv_drops_user(self):
        self.assertTrue(cli.tzdata_install("/v/bin/python", nt=False, venv=True)
                        .endswith("/v/bin/python -m pip install tzdata"))


if __name__ == "__main__":
    unittest.main()
