import glob
import os
import tempfile
import unittest

from tests.support import read, cli, fx, _tmp


def render(*extra):
    out = tempfile.mkdtemp(dir=_tmp)
    rc, so, se = cli("session", "--latest", "--tz", "UTC", "--claude-dir", fx("f_hostile"), "--out", out,
                     "--since", "2026-01-01", "--until", "2026-01-31", "--now", "2026-01-06T12:00:00Z",
                     "--format", "html,svg", *extra)
    assert rc == 0, se
    return {os.path.splitext(f)[1]: read(f) for f in glob.glob(os.path.join(out, "*"))}


class TestEscaping(unittest.TestCase):
    def test_model_name_is_escaped(self):
        for mode in ([], ["--private"]):
            for ext, text in render(*mode).items():
                with self.subTest(mode=mode, ext=ext):
                    self.assertNotIn("<script", text.lower())
                    self.assertNotIn("<img", text.lower())
                    self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)

    def test_private_project_path_is_escaped(self):
        for ext, text in render("--private").items():
            with self.subTest(ext=ext):
                self.assertNotIn("<img", text.lower())
                self.assertIn("-home-alice-&lt;img src=x&gt;", text)


if __name__ == "__main__":
    unittest.main()
