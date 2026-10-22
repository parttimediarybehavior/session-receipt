"""Shared test helpers.  Fixtures are synthetic only; real logs are never read."""
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tmp = tempfile.mkdtemp(prefix="sr_test_")
atexit.register(shutil.rmtree, _tmp, True)
os.environ["SESSION_RECEIPT_CACHE_DIR"] = os.path.join(_tmp, "cache")  # never touch ~/.cache

_spec = importlib.util.spec_from_file_location("make_fixtures", os.path.join(ROOT, "examples", "make_fixtures.py"))
mf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mf)
FIX = os.path.join(_tmp, "fixtures")
mf.build(FIX)

CCUSAGE_PRESENT = os.path.isfile(os.path.join(ROOT, "vendor", "node_modules", ".bin", "ccusage"))


def cli(*args, env=None):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run([sys.executable, "-m", "session_receipt"] + list(args), cwd=ROOT,
                       capture_output=True, text=True, env=e)
    return p.returncode, p.stdout, p.stderr


def cli_json(*args, env=None):
    """Run the CLI with --format json into a temp dir and return the parsed first file."""
    out = tempfile.mkdtemp(dir=_tmp)
    rc, so, se = cli(*args, "--out", out, "--format", "json", env=env)
    assert rc == 0, (rc, so, se)
    with open(os.path.join(out, sorted(os.listdir(out))[0])) as f:
        return json.load(f)


def fx(name):
    return os.path.join(FIX, name)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()
