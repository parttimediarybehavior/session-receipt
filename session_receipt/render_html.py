"""HTML receipt: the same SVG inline plus a details table.  Everything untrusted is escaped."""
from .render_svg import esc, render_svg, fmt_int, fmt_cost, SOURCE_TITLES, scope_lines, DISCLAIMER

CSS = ("body{font-family:-apple-system,'Segoe UI',Helvetica,Arial,'DejaVu Sans','Liberation Sans',sans-serif;max-width:640px;margin:1em auto;}"
       "table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #000;padding:3px 6px;"
       "text-align:right}th:first-child,td:first-child{text-align:left}h2{font-size:15px;margin:1em 0 .3em}")


def render_html(receipts, generated_at, private=False, show_env=False):
    svg = render_svg(receipts, generated_at, private, show_env)
    out = ['<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Session Receipt</title>'
           "<style>%s</style></head><body>" % CSS, svg, "<h1>Details</h1>"]
    for r in receipts:
        head, detail = scope_lines(r, private)
        out.append("<h2>%s: %s</h2>" % (esc(SOURCE_TITLES.get(r.source, r.source)), esc(head)))
        if private and r.project_path:
            out.append("<p>project: %s</p>" % esc(r.project_path))
        out.append("<table><tr><th>Model</th><th>Output</th><th>Fresh input</th><th>Cache writes</th>"
                   "<th>Cache reads</th><th>Reasoning (display only)</th><th>Est. cost</th><th>Price check</th></tr>")
        for m in r.models:
            out.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                       % (esc(m.name), fmt_int(m.output), fmt_int(m.input), fmt_int(m.cache_write),
                          fmt_int(m.cache_read), "" if m.reasoning is None else fmt_int(m.reasoning),
                          esc(fmt_cost(m.cost_usd)), esc(m.price_check)))
        out.append("</table>")
    out.append("<p>%s</p></body></html>" % esc(DISCLAIMER))
    return "".join(out)
