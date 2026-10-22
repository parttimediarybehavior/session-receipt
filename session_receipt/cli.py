"""session-receipt command line."""
import argparse
import importlib.util
import os
import sys
import tempfile
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import ccusage_adapter as ad
from . import export_json, pricecheck, prices, render_html, render_svg
from .ccusage_adapter import ReceiptError


class NotFound(ReceiptError):
    pass


def default_tz():
    tz = os.environ.get("TZ")
    if not tz:
        try:
            with open("/etc/timezone") as f:
                tz = f.read().strip()
        except OSError:
            tz = None
    return tz or "UTC"


def add_common(p):
    p.add_argument("--source", choices=["claude", "codex", "both"], default="claude")
    p.add_argument("--tz", default=default_tz())
    p.add_argument("--out", default="./receipts")
    p.add_argument("--format", default="html,svg,json", help="comma list of html,svg,json")
    p.add_argument("--env", action="store_true", help="add optional environmental scenarios")
    p.add_argument("--private", action="store_true",
                   help="keep project path and full session ID (local use only)")
    p.add_argument("--now", help="ISO time used as 'now' (default: real time)")
    p.add_argument("--claude-dir", help="CLAUDE_CONFIG_DIR (must contain projects/)")
    p.add_argument("--codex-home", help="CODEX_HOME")


def build_parser():
    ap = argparse.ArgumentParser(prog="session-receipt", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("session", help="receipt for one session")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--id", help="session ID, unique prefix, or the 6-hex 'session #' reference")
    g.add_argument("--latest", action="store_true", help="most recent lastActivity in the window (default)")
    s.add_argument("--since", help="YYYY-MM-DD: discovery window only; the receipt is the full session")
    s.add_argument("--until", help="YYYY-MM-DD: discovery window only; the receipt is the full session")
    add_common(s)
    d = sub.add_parser("daily", help="receipt for one calendar day")
    d.add_argument("--date", required=True, help="YYYY-MM-DD in --tz")
    add_common(d)
    m = sub.add_parser("demo", help="render the synthetic fixtures (no real logs needed)")
    m.add_argument("--out", default="./receipts-demo")
    m.add_argument("--now", help="ISO time used as 'now'")
    p = sub.add_parser("pricecheck", help="measure ccusage's effective rates vs the reference table")
    p.add_argument("--config", default=ad.OVERRIDES)
    p.add_argument("--model", action="append", help="full model name (default: all reference models)")
    u = sub.add_parser("update-prices", help="refresh prices from OpenRouter's public list (network, once)")
    u.add_argument("--from", dest="src", help="read a saved copy of %s instead of downloading" % prices.URL)
    return ap


def _sources(args):
    return ["claude", "codex"] if args.source == "both" else [args.source]


def _tz(name):
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ReceiptError("unknown timezone %r" % name)
    return name


def _finish(receipts, now):
    for r in receipts:
        ad.mark_provisional(r, now)
        pricecheck.apply_to_receipt(r)
    return receipts


def _match(r, ident):
    ident = ident.replace("session #", "").lstrip("#")
    return (r.session_id == ident or r.session_id.startswith(ident)
            or (len(ident) == 6 and r.short_id == ident))


def _fetch_sessions(source, args, tz, since, until):
    if source == "claude":
        return ad.fetch_claude_sessions(tz, since, until, claude_dir=args.claude_dir)
    return ad.fetch_codex_sessions(tz, since, until, codex_home=args.codex_home)


def select_sessions(args, now):
    """Pick session(s), then return each one's FULL history.

    --since/--until (or the default today+yesterday window for --latest) only choose WHICH
    session; ccusage filters records by date, so a windowed result for a resumed session is a
    partial slice. The selected session is therefore refetched without a window.
    """
    tz = _tz(args.tz)
    since, until = args.since, args.until
    if not args.id and not since and not until:
        today = now.astimezone(ZoneInfo(tz)).date()
        since, until = (today - timedelta(days=1)).isoformat(), today.isoformat()
    found = []
    for src in _sources(args):
        sessions = _fetch_sessions(src, args, tz, since, until)
        if args.id:
            hits = [r for r in sessions if _match(r, args.id)]
            if len(hits) > 1:
                raise ReceiptError("session id %r is ambiguous (%d matches)" % (args.id, len(hits)))
        else:
            hits = sorted(sessions, key=lambda r: r.window_end)[-1:]
        if hits and (since or until):
            full = {r.session_id: r for r in _fetch_sessions(src, args, tz, None, None)}
            hits = [full[r.session_id] for r in hits]
        found += hits
    if not found:
        if args.id:
            raise NotFound("session %r not found in source(s): %s" % (args.id, ", ".join(_sources(args))))
        raise NotFound("no sessions found for %s to %s (source(s): %s). Pass --since/--until or "
                       "--claude-dir/--codex-home." % (since, until, ", ".join(_sources(args))))
    return found


def select_daily(args):
    tz = _tz(args.tz)
    found = []
    for src in _sources(args):
        if src == "claude":
            days = ad.fetch_claude_daily(tz, args.date, args.date, claude_dir=args.claude_dir)
        else:
            days = ad.fetch_codex_daily(tz, args.date, args.date, codex_home=args.codex_home)
        found += [d for d in days if d.window_start == args.date]
    if not found:
        raise NotFound("no usage recorded for %s (%s) in source(s): %s"
                       % (args.date, tz, ", ".join(_sources(args))))
    return found


def emit(receipts, out_dir, name, fmts, now_iso, private, show_env):
    os.makedirs(out_dir, exist_ok=True)
    written = []
    renderers = {"svg": render_svg.render_svg, "html": render_html.render_html}
    for f in fmts:
        if f == "json":
            body = export_json.export(receipts, now_iso, private, show_env)
        elif f in renderers:
            body = renderers[f](receipts, now_iso, private, show_env)
        else:
            raise ReceiptError("unknown format %r (use html,svg,json)" % f)
        path = os.path.join(out_dir, "%s.%s" % (name, f))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        written.append(path)
    return written


def _fmts(s):
    return [x.strip() for x in s.split(",") if x.strip()]


def _iso(now):
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_session(args):
    now = ad.parse_now(args.now)
    rs = _finish(select_sessions(args, now), now)
    name = "session-" + "-".join(r.short_id for r in rs)
    return emit(rs, args.out, name, _fmts(args.format), _iso(now), args.private, args.env)


def cmd_daily(args):
    now = ad.parse_now(args.now)
    rs = _finish(select_daily(args), now)
    return emit(rs, args.out, "daily-" + args.date, _fmts(args.format), _iso(now), args.private, args.env)


def _load_fixture_builder():
    path = os.path.join(ad.ROOT, "examples", "make_fixtures.py")
    if not os.path.isfile(path):
        raise ReceiptError("demo needs examples/make_fixtures.py (not found at %s)" % path)
    spec = importlib.util.spec_from_file_location("sr_make_fixtures", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cmd_demo(args):
    now = ad.parse_now(args.now)
    iso = _iso(now)
    mf = _load_fixture_builder()
    written = []
    with tempfile.TemporaryDirectory(prefix="sr_demo_") as tmp:
        mf.build(tmp)
        f = lambda n: os.path.join(tmp, n)
        fm = ["html", "svg", "json"]

        def one(name, receipts, env=False):
            written.extend(emit(_finish(receipts, now), args.out, name, fm, iso, False, env))

        a = ad.fetch_claude_sessions("UTC", claude_dir=f("a_simple"))
        g = ad.fetch_codex_sessions("UTC", codex_home=f("g_codex/codex_home"))
        one("demo-simple", a + g, env=True)
        for r in ad.fetch_claude_sessions("UTC", claude_dir=f("b_concurrent")):
            one("demo-concurrent-" + r.short_id, [r])
        one("demo-subagent", ad.fetch_claude_sessions("UTC", claude_dir=f("c_subagent")))
        for d in ad.fetch_claude_daily("America/New_York", claude_dir=f("d_tz_boundary")):
            one("demo-tz-boundary-" + d.window_start, [d])
        one("demo-hostile", ad.fetch_claude_sessions("UTC", claude_dir=f("f_hostile")))
    for p in written:
        print(p)
    return written


def cmd_pricecheck(args):
    names = args.model or ["claude-" + k for k in pricecheck.load_reference()["models"]]
    bad = False
    for n in names:
        res = pricecheck.check_model(n, args.config)
        line = "%-24s %s" % (n, res["status"])
        if res["status"] == "mismatch":
            bad = True
            line += "  differing: " + ", ".join(
                "%s ccusage=%s list=%s" % (k, res["effective"][k], res["reference"][k])
                for k in res["differing"])
        print(line)
    return 1 if bad else 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "pricecheck":
            return cmd_pricecheck(args)
        if args.cmd == "update-prices":
            if args.src:
                with open(args.src, "rb") as f:
                    raw = f.read()
            else:
                raw = prices.fetch()
            prices.update(raw)
            return 0
        res = {"session": cmd_session, "daily": cmd_daily, "demo": cmd_demo}[args.cmd](args)
        if args.cmd != "demo":
            for p in res:
                print(p)
        return 0
    except NotFound as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    except ReceiptError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
