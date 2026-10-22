"""The static demo in docs/ must match what the tool renders today, and stay synthetic."""
import os, re, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
sys.path.insert(0, os.path.join(ROOT, "examples"))
import build_docs  # noqa: E402


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


class Docs(unittest.TestCase):
    def test_examples_are_current(self):
        with tempfile.TemporaryDirectory() as t:
            fresh = sorted(os.path.basename(p) for p in build_docs.build(t))
            self.assertEqual(fresh, sorted(os.listdir(os.path.join(DOCS, "examples"))))
            for n in fresh:
                self.assertEqual(read(os.path.join(t, n)), read(os.path.join(DOCS, "examples", n)),
                                 "%s is stale: run python3 examples/build_docs.py" % n)

    def test_default_example_has_no_scenarios(self):
        for n in ("claude-session.json", "codex-session.json"):
            self.assertNotIn("environmental_scenarios", read(os.path.join(DOCS, "examples", n)))
        self.assertIn("environmental_scenarios",
                      read(os.path.join(DOCS, "examples", "claude-session-with-scenarios.json")))

    def test_relative_links_resolve_and_nothing_private(self):
        index = read(os.path.join(DOCS, "index.html"))
        links = re.findall(r'(?:href|src)="([^"#]+)"', index)
        local = [l for l in links if not re.match(r"https?://", l)]
        self.assertGreaterEqual(len(local), 10)
        for l in local:
            self.assertTrue(os.path.isfile(os.path.join(DOCS, l)), l)
        self.assertNotIn("<script", index)
        for root, _, files in os.walk(DOCS):
            for f in files:
                if not f.endswith(".png"):
                    body = read(os.path.join(root, f))
                    self.assertNotRegex(body, r"/home/|/Users/|PLACEHOLDER", f)


if __name__ == "__main__":
    unittest.main()
