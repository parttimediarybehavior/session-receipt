"""Standalone SVG receipt (600 px wide, system fonts).  Every untrusted string is escaped."""
import html
import math
import textwrap
from datetime import datetime
from zoneinfo import ZoneInfo

from . import environment as env
from .ccusage_adapter import short_id
from . import pricecheck

WIDTH = 600
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, 'DejaVu Sans', 'Liberation Sans', sans-serif"
DISCLAIMER = "API list-price equivalent. Not what a subscription plan bills."
SOURCE_TITLES = {"claude": "CLAUDE CODE", "codex": "CODEX (experimental)"}


def esc(s):
    return html.escape(str(s), quote=True)


def fmt_int(n):
    return "{:,}".format(int(n))


def fmt_cost(x):
    if x is None:
        return "unknown"
    return "${:,.4f}".format(x) if abs(x) < 1000 else "${:,.2f}".format(x)


def fmt_sig(x):
    """Up to 3 significant figures, never scientific notation (receipts are read by people)."""
    if x == 0:
        return "0"
    if abs(x) >= 100:
        return "{:,.0f}".format(x)
    d = 2 - int(math.floor(math.log10(abs(x))))
    return ("{:.%df}" % max(d, 0)).format(x)


# Scale environmental units so small sessions read as "0.95 Wh", not "0.000946 kWh".
ENV_UNITS_LARGE = (("kwh", "kWh", 1), ("litres", "litres water", 1), ("kg_co2e", "kg CO2e", 1))
ENV_UNITS_SMALL = (("kwh", "Wh", 1000), ("litres", "mL water", 1000), ("kg_co2e", "g CO2e", 1000))


def env_units(sc):
    return ENV_UNITS_SMALL if sc["high"]["kwh"] < 1 else ENV_UNITS_LARGE


def fmt_rate(x):
    """A per-MTok price in currency style: 0.1 -> 0.10, 4 -> 4.00, 0.625 -> 0.625."""
    t = "{:.3f}".format(x)
    return t[:-1] if t.endswith("0") else t


def trunc(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


def fmt_time(iso, tz):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


def scope_lines(r, private):
    """(headline, detail) for the Serving size line.  Public never shows ids' raw form."""
    if r.kind == "daily":
        return r.label, None
    ident = ("session %s" % r.session_id) if private else ("session #%s" % short_id(r.session_id))
    head = "one session (%s)" % ident
    if r.source == "claude" and r.window_start:
        detail = "%s to %s (%s)" % (fmt_time(r.window_start, r.tz), fmt_time(r.window_end, r.tz), r.tz)
    else:
        detail = "last activity %s (%s)" % (fmt_time(r.window_end, r.tz), r.tz) if r.window_end else None
    return head, detail


def counts_scope(receipts):
    """What the counts include, per source. Claude subagent transcripts belong to their session;
    each Codex subagent thread is its own rollout, so ccusage makes it a separate session."""
    bits = []
    if any(r.source == "claude" for r in receipts):
        bits.append("Claude Code counts include subagents; streamed duplicates removed.")
    codex = [r for r in receipts if r.source == "codex"]
    if any(r.kind == "session" for r in codex):
        bits.append("Codex subagent threads are separate sessions, not included in a Codex session receipt.")
    elif codex:
        bits.append("Codex daily counts include subagent threads.")
    return " ".join(bits)


class Canvas:
    def __init__(self):
        self.parts = []
        self.y = 0

    def text(self, x, y, s, size=12, weight="normal", anchor="start", fill="#000", extra=""):
        self.parts.append(
            '<text x="%s" y="%s" font-size="%s" font-weight="%s" text-anchor="%s" fill="%s"%s>%s</text>'
            % (x, y, size, weight, anchor, fill, extra, esc(s)))

    def rect(self, x, y, w, h, fill="#000", stroke="none", sw=0, dash=None):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        self.parts.append('<rect x="%s" y="%s" width="%s" height="%s" fill="%s" stroke="%s" '
                          'stroke-width="%s"%s/>' % (x, y, w, h, fill, stroke, sw, d))

    def rule(self, y, h, x=16, w=WIDTH - 32):
        self.rect(x, y, w, h)

    def line(self, s, size=12, weight="normal", x=20, fill="#000", gap=None):
        self.y += gap if gap else int(size * 1.45)
        self.text(x, self.y, s, size, weight, fill=fill)

    def wrapped(self, s, chars=86, **kw):
        for ln in textwrap.wrap(s, chars) or [""]:
            self.line(ln, **kw)


def _numbers_row(c, y, name, vals, weight="normal", size=12):
    c.text(22, y, trunc(name, 22), size, weight)
    for xr, v in zip((300, 385, 470, 580), vals):
        c.text(xr, y, fmt_int(v), size, weight, anchor="end")


def _block(c, r, private, show_env, notes):
    # source band
    c.y += 10
    c.rect(16, c.y, WIDTH - 32, 22)
    c.text(24, c.y + 16, SOURCE_TITLES.get(r.source, r.source.upper()), 14, "bold", fill="#fff")
    c.y += 22
    head, detail = scope_lines(r, private)
    c.y += 4
    c.line("", gap=2)
    c.text(20, c.y + 14, "Serving size", 13, "bold")
    c.text(118, c.y + 14, head, 13)
    c.y += 14
    if detail:
        c.line(detail, 11, fill="#444")
    if private and r.project_path:
        c.line("project: " + r.project_path, 11, fill="#444")
    if private and r.session_dir:
        c.line("directory: " + r.session_dir, 11, fill="#444")
    if r.provisional:
        c.line("PROVISIONAL: session may still be running; later usage not included.", 12, "bold", gap=20)
    c.y += 6
    c.rule(c.y, 8)
    c.y += 8

    # (A) recorded usage
    c.line("A. RECORDED USAGE", 15, "bold", gap=22)
    out_hdr = "incl. reasoning" if r.source == "codex" else "incl. thinking"
    c.y += 8
    y1 = c.y + 10
    for xr, a, b in ((300, "Output", out_hdr), (385, "Fresh", "input"), (470, "Cache", "writes"),
                     (580, "Cache", "reads")):
        c.text(xr, y1, a, 11, "bold", anchor="end")
        c.text(xr, y1 + 12, b, 10, anchor="end", fill="#333")
    c.text(22, y1, "Model", 11, "bold")
    c.y = y1 + 16
    c.rule(c.y, 2)
    for m in r.models:
        c.y += 17
        _numbers_row(c, c.y, m.name, (m.output, m.input, m.cache_write, m.cache_read))
    c.y += 6
    c.rule(c.y, 4)
    c.y += 17
    t = r.totals
    _numbers_row(c, c.y, "Subtotal", (t["output"], t["input"], t["cache_write"], t["cache_read"]), "bold")
    if r.source == "codex":
        c.line("of which reasoning: %s (already inside Output; not added again)"
               % fmt_int(t.get("reasoning", 0)), 10, fill="#444")
        cc = r.count_check or {}
        if cc.get("status") == "undercount":
            c.wrapped("undercount: the Codex logs record %s tokens that ccusage did not count (a ccusage "
                      "gap seen with some subagent threads). The counts and cost on this receipt exclude them."
                      % fmt_int(cc["missing_tokens"]), 96, size=10, weight="bold")
        elif cc.get("status") == "mismatch":
            c.wrapped("count check: ccusage counted %s more tokens than the Codex logs' per-response records "
                      "show, so those could not be checked." % fmt_int(cc.get("extra_tokens", 0)),
                      96, size=10, fill="#444")
        elif cc.get("status") == "incomplete":
            c.wrapped("count check incomplete: %s Codex log record(s) could not be read or dated."
                      % fmt_int(cc.get("skipped_records", 0)), 96, size=10, fill="#444")
    c.line("Counts are tokens as recorded in local logs, per provider; not comparable across providers.",
           10, fill="#444")
    c.y += 8
    c.rule(c.y, 8)
    c.y += 8

    # (B) estimated cost
    c.line("B. ESTIMATED COST", 15, "bold", gap=22)
    c.line(DISCLAIMER, 11, "bold")
    c.y += 4
    for m in r.models:
        c.y += 17
        c.text(22, c.y, trunc(m.name, 30), 12)
        if m.cost_usd is None:
            if r.source == "codex" and m.name not in r.unpriced and len(r.models) > 1:
                s = "see subtotal"
            else:
                s = "unknown"
        elif m.price_check == "mismatch":
            notes.append(m)
            s = "%s ⚠%d" % (fmt_cost(m.cost_usd), len(notes))
        else:
            s = fmt_cost(m.cost_usd)
        c.text(580, c.y, s, 12, anchor="end")
    c.y += 6
    c.rule(c.y, 4)
    c.y += 17
    priced = [m for m in r.models if m.cost_usd is not None]
    c.text(22, c.y, "Subtotal (%s)" % SOURCE_TITLES.get(r.source, r.source).split(" (")[0].title(), 12, "bold")
    if r.source == "codex":
        total = fmt_cost(t["cost_usd"]) if t.get("cost_usd") is not None else "unknown"
    else:
        total = fmt_cost(t["cost_usd"]) if priced else "unknown"
    c.text(580, c.y, total, 12, "bold", anchor="end")
    if r.unpriced:
        c.line("partial: excludes %d unpriced model(s)" % len(r.unpriced), 11, "bold")
    unverified = [m.name for m in r.models if m.price_check == "unverified" and m.name not in r.unpriced]
    if unverified:
        c.wrapped("unverified: prices for %s come from ccusage's table and were not checked against a published list."
                  % ("these models" if len(unverified) > 1 else unverified[0]), 100, size=10, fill="#444")
    c.y += 6

    # (C) optional environmental scenarios
    if show_env:
        _env_block(c, r)


def _env_block(c, r):
    c.y += 10
    top = c.y
    c.y += 4
    c.line("Illustrative scenarios, not measurements", 12, "bold", x=28, fill="#666")
    c.line("C. OPTIONAL ENVIRONMENTAL SCENARIOS (%s tokens only)" % r.source, 10, x=28, fill="#666")
    sc = env.scenarios(r.totals)
    c.y += 6
    ys = c.y + 8
    units = env_units(sc)
    for xr, (_, h, _m) in zip((300, 430, 570), units):
        c.text(xr, ys, h, 10, "bold", anchor="end", fill="#555")
    c.y = ys
    for lv in env.LEVELS:
        c.y += 15
        c.text(28, c.y, lv.upper(), 10, fill="#555")
        for xr, (k, _h, mult) in zip((300, 430, 570), units):
            c.text(xr, c.y, fmt_sig(sc[lv][k] * mult), 10, anchor="end", fill="#555")
    c.line(env.NOT_BOUNDS + " LOW/HIGH are scenarios built on cited estimates and flagged assumptions.",
           9, x=28, fill="#666")
    c.line("Sources: %s; see SOURCES.md. ASSUMPTION-flagged values have no source." % ", ".join(env.SOURCE_KEYS),
           9, x=28, fill="#666")
    c.y += 6
    c.rect(22, top, WIDTH - 44, c.y - top, fill="none", stroke="#888", sw=1.5, dash="5,4")
    c.y += 4


def render_svg(receipts, generated_at, private=False, show_env=False):
    """receipts: list of Receipt, one per source (own block each; no cross-provider total)."""
    c = Canvas()
    c.text(20, 54, "Session Receipt", 38, "bold")
    c.text(20, 74, "See what this work used, what's included, and where the numbers came from.", 11, fill="#333")
    c.rect(16, 84, WIDTH - 32, 10)
    c.y = 94
    notes = []
    for r in receipts:
        _block(c, r, private, show_env, notes)
    # footer
    c.y += 4
    c.rule(c.y, 10)
    c.y += 10
    c.line("Where the numbers came from", 14, "bold", gap=22)
    r0 = receipts[0]
    prov = r0.pricing_provenance
    status = pricecheck.summary_status(receipts)
    c.wrapped("Counts: %s. %s" % (r0.tool_version, counts_scope(receipts)), size=10)
    c.wrapped("Prices: checked against the %s as of %s: %s. Codex/OpenAI prices are not checked yet "
              "and are unverified." % (prov.get("source", "?"), prov.get("as_of", "?"), status), size=10)
    c.wrapped("Timezone: %s. Generated at: %s." % (r0.tz, generated_at), size=10)
    if any(r.provisional for r in receipts):
        c.wrapped("PROVISIONAL: session may still be running; later usage not included.", size=10, weight="bold")
    for i, m in enumerate(notes, 1):
        d = m.price_detail or {}
        eff, ref = d.get("effective", {}), d.get("reference", {})
        bits = ["%s: ccusage charges $%s/MTok, %s is $%s/MTok"
                % (k, fmt_rate(eff[k]) if eff.get(k) is not None else "nothing",
                   prov.get("source", "the list"), fmt_rate(ref[k]))
                for k in d.get("differing", [])]
        c.wrapped("⚠%d %s price mismatch: %s." % (i, m.name, "; ".join(bits)), size=10)
    c.line(DISCLAIMER, 10, "bold")
    c.y += 14
    h = c.y
    body = "".join(c.parts)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
            'font-family="%s" role="img" aria-label="Session Receipt">'
            '<rect x="0" y="0" width="%d" height="%d" fill="#fff"/>'
            '<rect x="3" y="3" width="%d" height="%d" fill="none" stroke="#000" stroke-width="6"/>%s</svg>'
            % (WIDTH, h, WIDTH, h, esc(FONT), WIDTH, h, WIDTH - 6, h - 6, body))
