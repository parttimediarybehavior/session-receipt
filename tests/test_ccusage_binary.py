"""Which ccusage executable runs: SESSION_RECEIPT_CCUSAGE, else the installed native build.

Windows selection is tested on every OS against fake package trees: npm installs the build for
Node's process.arch, which need not match the machine type Python reports.
"""
import os
import stat
import tempfile
import unittest
from unittest import mock

from session_receipt import ccusage_adapter as ad


class WindowsBinary(unittest.TestCase):
    def modules(self, *archs, base=None):
        d = base or tempfile.mkdtemp()
        for a in archs:
            p = os.path.join(d, "@ccusage", "ccusage-win32-" + a, "bin")
            os.makedirs(p)
            open(os.path.join(p, "ccusage.exe"), "w").close()
        return d

    def pick(self, machine, *installed):
        m = self.modules(*installed)
        return os.path.relpath(ad.windows_binary(m, machine), m).replace(os.sep, "/")

    def test_x64(self):
        self.assertEqual(self.pick("AMD64", "x64"), "@ccusage/ccusage-win32-x64/bin/ccusage.exe")

    def test_arm64(self):
        self.assertEqual(self.pick("ARM64", "arm64"), "@ccusage/ccusage-win32-arm64/bin/ccusage.exe")

    def test_arm64_prefers_native_when_both_installed(self):
        self.assertEqual(self.pick("ARM64", "arm64", "x64"), "@ccusage/ccusage-win32-arm64/bin/ccusage.exe")

    def test_arm64_machine_with_x64_node_uses_installed_x64(self):
        # ARM64 Python, x64 Node: npm installed the x64 build, which runs under emulation.
        self.assertEqual(self.pick("ARM64", "x64"), "@ccusage/ccusage-win32-x64/bin/ccusage.exe")

    def test_x64_machine_with_only_arm64_installed_is_refused(self):
        # An x64 machine type (native x64, or x64 Python emulated on Arm) cannot be assumed to
        # run an ARM64 build, so it is never picked.
        with self.assertRaises(ad.ReceiptError) as e:
            self.pick("AMD64", "arm64")
        self.assertIn("installed: arm64", str(e.exception))
        self.assertIn("SESSION_RECEIPT_CCUSAGE", str(e.exception))

    def test_missing_binary(self):
        with self.assertRaises(ad.ReceiptError) as e:
            self.pick("AMD64")
        self.assertIn("ccusage binary not found", str(e.exception))
        self.assertIn("installed: none", str(e.exception))

    def test_unknown_machine_gets_no_guess(self):
        with self.assertRaises(ad.ReceiptError):
            self.pick("x86", "x64", "arm64")

    def test_default_binary_on_windows_uses_reported_machine(self):
        root = tempfile.mkdtemp()
        m = self.modules("x64", base=os.path.join(root, "vendor", "node_modules"))
        with mock.patch.object(ad, "ROOT", root), mock.patch.object(ad.os, "name", "nt"), \
                mock.patch.object(ad.platform, "machine", return_value="ARM64"):
            self.assertEqual(ad._default_binary(),
                             os.path.join(m, "@ccusage", "ccusage-win32-x64", "bin", "ccusage.exe"))


class Override(unittest.TestCase):
    def test_env_override_wins_and_skips_selection(self):
        exe = os.path.join(tempfile.mkdtemp(), "my ccusage")
        open(exe, "w").close()
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IXUSR)
        with mock.patch.dict(os.environ, {"SESSION_RECEIPT_CCUSAGE": exe}), \
                mock.patch.object(ad, "_default_binary", side_effect=AssertionError("not used")):
            self.assertEqual(ad.find_binary(), exe)

    def test_env_override_must_exist(self):
        with mock.patch.dict(os.environ, {"SESSION_RECEIPT_CCUSAGE": "/nonexistent/ccusage"}):
            with self.assertRaises(ad.ReceiptError):
                ad.find_binary()


if __name__ == "__main__":
    unittest.main()
