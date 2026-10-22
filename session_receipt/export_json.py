"""Normalised Receipt -> JSON (schema session-receipt/1).  Public by default."""
import json
from dataclasses import asdict

from .ccusage_adapter import short_id, ReceiptError
from .render_svg import scope_lines
from . import environment as env

SCHEMA = "session-receipt/1"
FORBIDDEN_PUBLIC_KEYS = {"cwd", "projectPath", "project_path", "directory", "session_dir", "session_file",
                         "sessionFile", "session_id", "sessionId", "message", "content", "prompt", "text"}


def _assert_clean(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in FORBIDDEN_PUBLIC_KEYS:
                raise ReceiptError("refusing to export private field %r in public mode" % k)
            _assert_clean(v)
    elif isinstance(o, list):
        for v in o:
            _assert_clean(v)


def receipt_dict(r, private=False, show_env=False):
    d = asdict(r)
    for k in ("session_id", "project_path", "session_dir", "session_file"):
        d.pop(k, None)
    if r.kind == "session":
        d["label"] = scope_lines(r, False)[0]
        d["session_ref"] = "session #%s" % short_id(r.session_id)
    if private:
        d.update(session_id=r.session_id, project_path=r.project_path,
                 session_dir=r.session_dir, session_file=r.session_file)
        if r.kind == "session":
            d["label"] = scope_lines(r, True)[0]
    if show_env:
        d["environmental_scenarios"] = {
            "caveat": env.CAVEAT, "note": env.NOT_BOUNDS, "source_keys": list(env.SOURCE_KEYS),
            "unit": {"kwh": "kWh", "litres": "litres", "kg_co2e": "kg CO2e"},
            "levels": env.scenarios(r.totals)}
    return d


def export(receipts, generated_at, private=False, show_env=False):
    doc = {"schema": SCHEMA, "generated_at": generated_at,
           "privacy": "private" if private else "public",
           "disclaimer": "API list-price equivalent. Not what a subscription plan bills.",
           "receipts": [receipt_dict(r, private, show_env) for r in receipts]}
    if not private:
        _assert_clean(doc)
    # "<" escaped as \u003c (still valid JSON) so the file is inert if ever opened as HTML
    return json.dumps(doc, indent=2, sort_keys=True).replace("<", "\\u003c") + "\n"
