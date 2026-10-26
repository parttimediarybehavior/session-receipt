"""One version everywhere: plugin.json is what Claude Code compares to decide whether users get
an update, so the npm, Python and package versions must match it, and marketplace.json must not
set its own (Claude Code would quietly prefer plugin.json's)."""
import json
import os
import re
import unittest

from session_receipt import __version__
from tests.support import ROOT


def load(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def pyproject_version():
    m = re.search(r'^\[project\]$.*?^version = "([^"]+)"$', load("pyproject.toml"), re.M | re.S)
    return m.group(1) if m else None


class SameVersionEverywhere(unittest.TestCase):
    def test_versions_match_plugin_json(self):
        plugin = json.loads(load(".claude-plugin", "plugin.json"))["version"]
        self.assertRegex(plugin, r"^\d+\.\d+\.\d+$")
        lock = json.loads(load("package-lock.json"))
        found = {
            "package.json": json.loads(load("package.json"))["version"],
            "package-lock.json": lock["version"],
            "package-lock.json packages['']": lock["packages"][""]["version"],
            "pyproject.toml": pyproject_version(),
            "session_receipt.__version__": __version__,
        }
        self.assertEqual({k: v for k, v in found.items() if v != plugin}, {},
                         "these differ from .claude-plugin/plugin.json (%s)" % plugin)

    def test_marketplace_entry_sets_no_version(self):
        for entry in json.loads(load(".claude-plugin", "marketplace.json"))["plugins"]:
            self.assertNotIn("version", entry, entry["name"])


if __name__ == "__main__":
    unittest.main()
