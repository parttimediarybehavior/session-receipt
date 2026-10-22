import glob
import os
import re
import tempfile
import unittest

from tests.support import read, cli, fx, FIX, _tmp

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CASES = [("a_simple", "claude-dir"), ("b_concurrent", "claude-dir"), ("c_subagent", "claude-dir"),
         ("d_tz_boundary", "claude-dir"), ("f_hostile", "claude-dir"), ("g_codex/codex_home", "codex-home")]


def render(fixture, flag, *extra):
    out = tempfile.mkdtemp(dir=_tmp)
    src = ["--source", "codex"] if flag == "codex-home" else []
    rc, so, se = cli("session", "--latest", "--tz", "UTC", "--" + flag, fx(fixture), "--out", out,
                     "--since", "2026-01-01", "--until", "2026-01-31", "--now", "2026-01-06T12:00:00Z",
                     "--env", *src, *extra)
    assert rc == 0, (rc, se)
    files = sorted(glob.glob(os.path.join(out, "*")))
    assert len(files) == 3, files
    return {os.path.splitext(f)[1]: read(f) for f in files}


class TestPrivacy(unittest.TestCase):
    def test_public_exports_leak_nothing(self):
        for fixture, flag in CASES:
            texts = render(fixture, flag)
            for ext, text in texts.items():
                with self.subTest(fixture=fixture, ext=ext):
                    self.assertNotIn("alice", text.lower())
                    self.assertNotIn("/home/", text)
                    self.assertNotIn("secret-project", text)
                    self.assertNotIn("PRIVATE-SAMPLE-TEXT", text)
                    self.assertIsNone(UUID.search(text), "full session UUID leaked")
                    self.assertIn("session #", text)

    def test_private_mode_keeps_paths_and_ids(self):
        # positive control: proves the public test above is not vacuous
        texts = render("a_simple", "claude-dir", "--private")
        self.assertIn("aaaaaaaa-1111-4111-8111-000000000001", texts[".json"])
        self.assertIn("-home-alice-secret-project", texts[".json"])
        self.assertIn("aaaaaaaa-1111-4111-8111-000000000001", texts[".svg"])
        self.assertNotIn("PRIVATE-SAMPLE-TEXT", "".join(texts.values()))   # content never present

    def test_session_ref_is_first_six_hex_of_sha256(self):
        # sha256("aaaaaaaa-1111-4111-8111-000000000001") begins 6a9871 (hash, computed with sha256sum)
        texts = render("a_simple", "claude-dir")
        self.assertIn("session #6a9871", texts[".svg"])


if __name__ == "__main__":
    unittest.main()
