"""bin/ launchers and `doctor`: run the CLI from a checkout or plugin with no pip install."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
