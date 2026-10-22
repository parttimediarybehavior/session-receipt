import glob
import os
import re
import tempfile
import unittest

from tests.support import read, cli, fx, _tmp

ZERO = re.compile(r"\$0\.0+(?![0-9])")   # exactly-zero dollar amounts such as $0.00 / $0.0000


def render(fixture):
    out = tempfile.mkdtemp(dir=_tmp)
    rc, so, se = cli("session", "--latest", "--tz", "UTC", "--claude-dir", fx(fixture), "--out", out,
                     "--since", "2026-01-01", "--until", "2026-01-31", "--now", "2026-01-06T12:00:00Z",
                     "--format", "html,svg")
    assert rc == 0, se
    return {os.path.splitext(f)[1]: read(f) for f in glob.glob(os.path.join(out, "*"))}


class TestUnknownPrice(unittest.TestCase):
    def test_mixed_session_is_partial(self):
        for ext, text in render("a_simple").items():
            with self.subTest(ext=ext):
                self.assertIn("mystery-model-9", text)
                self.assertIn("unknown", text)
                self.assertIn("partial: excludes 1 unpriced model(s)", text)
                self.assertIsNone(ZERO.search(text), "an unknown price was shown as zero dollars")

    def test_all_unpriced_total_is_unknown(self):
        svg = render("f_hostile")[".svg"]
        self.assertIn("partial: excludes 1 unpriced model(s)", svg)
        self.assertIsNone(ZERO.search(svg))
        # model line and subtotal line both read "unknown"
        self.assertEqual(svg.count(">unknown<"), 2)

    def test_zero_regex_is_not_vacuous(self):
        self.assertTrue(ZERO.search("cost $0.0000"))
        self.assertFalse(ZERO.search("cost $0.0077"))


if __name__ == "__main__":
    unittest.main()
