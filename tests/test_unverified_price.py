"""A priced-but-unchecked model (Codex/OpenAI: no reference list) must say so next to its subtotal."""
import os, re, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestUnverifiedPrice(unittest.TestCase):
    def test_codex_subtotal_is_marked_unverified(self):
        out = tempfile.mkdtemp()
        env = dict(os.environ, SESSION_RECEIPT_CACHE_DIR=tempfile.mkdtemp())
        r = subprocess.run([sys.executable, "-m", "session_receipt", "demo", "--out", out, "--now", "2026-01-06T12:00:00Z"],
                           cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        svg = open(os.path.join(out, "demo-simple.svg"), encoding="utf-8").read()
        visible = " ".join(re.findall(r"<text[^>]*>([^<]*)</text>", svg))
        self.assertIn("unverified: prices for gpt-5 come from ccusage&#x27;s table", visible)
        # Claude models with a reference entry are not labelled unverified
        self.assertNotIn("prices for claude-sonnet-5-5 come from", visible)


if __name__ == "__main__":
    unittest.main()
