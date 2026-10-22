"""Regenerate the static demo's example receipts in docs/examples/ from the synthetic fixtures.

    python3 examples/build_docs.py            # writes docs/examples/*.{html,svg,json}
    python3 examples/build_docs.py --png      # also screenshots docs/preview.png (needs headless Chromium)

Everything is synthetic (examples/make_fixtures.py): fake paths, fake prompts, fake usage.
No real logs are read. docs/index.html itself is hand-written and is not touched.
"""
import argparse
import glob
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from session_receipt import ccusage_adapter as ad  # noqa: E402
from session_receipt import cli  # noqa: E402

NOW = "2026-01-06T12:00:00Z"
OUT = os.path.join(ROOT, "docs", "examples")
FORMATS = ["html", "svg", "json"]


def build(out=OUT):
    now = ad.parse_now(NOW)
    written = []
    with tempfile.TemporaryDirectory(prefix="sr_docs_") as tmp:
        cli._load_fixture_builder().build(tmp)
        claude = ad.fetch_claude_sessions("UTC", claude_dir=os.path.join(tmp, "a_simple"))
        codex = ad.fetch_codex_sessions("UTC", codex_home=os.path.join(tmp, "g_codex", "codex_home"))
        for name, receipts, env in (("claude-session", claude, False),
                                    ("codex-session", codex, False),
                                    ("claude-session-with-scenarios", claude, True)):
            written += cli.emit(cli._finish(receipts, now), out, name, FORMATS, NOW, False, env)
    return written


def find_chromium():
    env = os.environ.get("SESSION_RECEIPT_CHROMIUM")
    if env:
        return env
    hits = sorted(glob.glob(os.path.expanduser(
        "~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")))
    return hits[-1] if hits else None


def screenshot(svg, png):
    chrome = find_chromium()
    if not chrome:
        raise SystemExit("no headless Chromium found; set SESSION_RECEIPT_CHROMIUM")
    subprocess.run([chrome, "--headless", "--no-sandbox", "--hide-scrollbars", "--disable-gpu",
                    "--window-size=600,591", "--screenshot=" + png, "file://" + svg],
                   check=True, capture_output=True)
    return png


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", action="store_true")
    a = ap.parse_args()
    paths = build()
    if a.png:
        paths.append(screenshot(os.path.join(OUT, "claude-session.svg"),
                                os.path.join(ROOT, "docs", "preview.png")))
    for p in paths:
        print(os.path.relpath(p, ROOT))
