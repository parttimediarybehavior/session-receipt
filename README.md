# Session Receipt v1

See what this work used, what's included, and where the numbers came from.

![Example receipt for a synthetic Claude Code session: recorded tokens per model, an API list-price equivalent cost, and one model with no known price, so the total is marked partial](docs/preview.png)

[Live demo](https://parttimediarybehavior.github.io/session-receipt/) with example HTML/SVG/JSON receipts (all synthetic), also available locally at [`docs/index.html`](docs/index.html).
Regenerate the examples with `python3 examples/build_docs.py --png`.

A local command-line tool that turns your Claude Code (and, experimentally, Codex) usage logs
into a nutrition-label style receipt: recorded token usage, an API-equivalent cost estimate,
and (optionally) illustrative environmental scenarios. Accounting is plain deterministic code.
There are no model calls, and receipts make no network calls (the one-time `npm ci` below
downloads ccusage from the npm registry; `update-prices` downloads the price list, only when
you run it).

## Install (from source)

```
git clone https://github.com/parttimediarybehavior/session-receipt.git
cd session-receipt
npm ci --prefix vendor                 # installs the pinned ccusage 20.0.38 (MIT)
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/session-receipt demo --out /tmp/sr_demo --now 2026-01-06T12:00:00Z   # synthetic demo
```

Editable/source install only; no wheel is published. Python 3.10+ standard library only, plus
Node.js for `npm ci` (tested with Node 18.19). ccusage ships a native binary per platform
(darwin/linux/win32, x64/arm64); **only Linux x64 has been tested.** For an offline machine, run
`npm ci --prefix vendor` elsewhere and copy `vendor/node_modules/` across, or point
`SESSION_RECEIPT_CCUSAGE` at an existing ccusage 20.0.38. Uninstall: `pip uninstall
session-receipt` and delete the project directory (nothing is written outside it except the
optional price-check cache in `~/.cache/session-receipt/`, or `$SESSION_RECEIPT_CACHE_DIR`).
You can also run it without installing: `python3 -m session_receipt ...` from the project root.

## Try it with no real logs

```
python3 -m session_receipt demo --out /tmp/sr_demo --now 2026-01-06T12:00:00Z
```

This builds synthetic fixtures (fake paths, fake content) and renders HTML, SVG and JSON.

## Report on real usage

```
python3 -m session_receipt session --latest --tz America/New_York
python3 -m session_receipt session --id <id-or-prefix-or-6hex> --env
python3 -m session_receipt daily --date 2026-10-20 --tz America/New_York --source both
python3 -m session_receipt pricecheck
```

Options: `--source claude|codex|both`, `--format html,svg,json`, `--out DIR` (default `./receipts/`),
`--env`, `--private`, `--now ISO`, `--claude-dir` (a dir containing `projects/`),
`--codex-home`. `--latest` means the most recent last activity within today and yesterday
(or `--since/--until`). A missing session exits non-zero with a message.

`--tz` defaults to `$SESSION_RECEIPT_TZ`, then `$TZ`, then the system zone (`/etc/timezone`, or
the zone `/etc/localtime` links to, as on macOS and Fedora), else `UTC`. Automatic receipts
(the hook, below) use the same default. Windows has neither file, so set `SESSION_RECEIPT_TZ`
there (`[Environment]::SetEnvironmentVariable("SESSION_RECEIPT_TZ", "America/Chicago", "User")`)
rather than `TZ`, which other Windows programs read in a different format.

## Offline

ccusage always runs with `--offline` (bundled price table). Making a receipt fetches nothing.
Your logs are only read, never modified.

## Prices: a dated snapshot, refreshed on request

```
python3 -m session_receipt update-prices            # downloads https://openrouter.ai/api/v1/models once
python3 -m session_receipt update-prices --from models.json   # or use a saved copy
```

This writes three files under `pricing/`, all stamped with the download date:
`openrouter-snapshot.json` (the published Anthropic and OpenAI entries), `reference.json`
(Claude rates per MTok, including long-prompt tiers) and `ccusage-overrides.json`. It then
measures ccusage's built-in rate for every Claude model against the snapshot. Where they
disagree it writes an override, so receipts are costed at the snapshot's prices. Models with a
long-prompt tier are never overridden, because a flat override would erase the tier; a
disagreement there stays on the receipt as a warning. The receipt footer says
"checked against the OpenRouter list as of <date>". Prices are only as current as the last
`update-prices`. On 2026-10-21, ccusage agreed with OpenRouter on all 15 Claude models and all
five rate types, so no overrides were needed. OpenRouter passes Anthropic's list prices through;
a spot check against Anthropic's pricing page that day agreed. The tool never writes under `~/.claude` or `~/.codex`.

## How to read the receipt

- **A. Recorded usage**: tokens per model as recorded: output (including thinking/reasoning),
  fresh input, cache writes, cache reads. Each provider has its own block and subtotal;
  there is deliberately no cross-provider grand total because token semantics differ.
- **B. Estimated cost**: tokens times list prices. It is an API-equivalent estimate, not what a
  subscription plan bills. An unpriced model reads "unknown" (never $0) and the subtotal says
  "partial: excludes N unpriced model(s)".
- **C. Optional environmental scenarios** (only with `--env`): LOW / CENTRAL / HIGH for kWh,
  litres of water and kg CO2e. These are illustrative scenarios built from cited estimates and
  flagged assumptions. None is measured and they are not bounds. Sources: `session_receipt/SOURCES.md`.
- **Where the numbers came from**: ccusage version, price table date and check status, timezone,
  generation time. Counts include subagents; streamed duplicates are removed.
- **PROVISIONAL** appears when the last activity is within 2 minutes of generation time, or the
  window includes today.
- **Price check**: `pricecheck` measures the rates ccusage actually applies (five probe
  fixtures per model) and compares them with `pricing/reference.json`. Mismatches are marked
  with a warning sign and a footnote.

## Privacy defaults

Public export is the default. It omits prompt/response content (ccusage never emits it, and
the tool refuses output containing such fields), usernames, filesystem paths (project path,
cwd, directory), and raw session IDs (shown as `session #<first 6 hex of sha256(id)>`).
`--private` keeps the project path and full session ID for local use only. Model names are
always escaped before they reach HTML or SVG.

## Supported / not supported in v1

- Session and daily receipts for Claude Code: supported.
- Concurrent sessions are kept separate by session id. Subtracting machine-wide totals is never
  used for attribution (it is wrong when sessions overlap).
- Codex: **experimental**. Works with synthetic rollouts in tests (ccusage reads `CODEX_HOME`).
  Per-model cost is shown only when a session used one model; otherwise only the session cost.
  Codex prices are not checked against the snapshot yet, so they read "unverified". A model
  ccusage cannot price reads "unknown" and the subtotal is partial (or unknown if no model in
  it is priced). Allocating cost across models is never guessed.
- **Turn-level attribution: not supported.** Usage is recorded per streamed API message, not
  per user turn; a turn spans several messages and subagents, and ccusage exposes no turn
  boundaries. Task attribution across sessions is also out of scope.
- The 5-minute vs 1-hour cache-write split is not exposed by ccusage's JSON; the price check
  verifies the 1h rate with a probe but receipts show one cache-write column.
- Long-prompt tiers (e.g. haiku-5-5 above 100K) are applied by ccusage and recorded in the
  reference, but the price check probes only the standard tier.

## Claude Code plugin (optional)

`integrations/claude-code/session-receipt/` is a Claude Code plugin with:

- a `/session-receipt:receipt` skill: asks Claude to run this CLI for the current session
  (`${CLAUDE_SESSION_ID}`), today, or a date. Claude reports what the CLI printed; it does not
  count anything itself. A receipt for the *current* session is provisional: it cannot include
  the reply that reports it.
- an optional **SessionEnd** hook that writes a receipt when a session ends. It is **inert unless
  you opt in**: `mkdir -p ~/.config/session-receipt && touch ~/.config/session-receipt/auto-enabled`
  (or `SESSION_RECEIPT_AUTO=1`). `touch ~/.config/session-receipt/disabled` always turns it off.
  The hook returns in milliseconds and does the work in a detached process that first waits for
  the transcript to stop changing. It never calls a model or starts Claude Code, so it cannot
  trigger a turn; a nested-run guard (`SESSION_RECEIPT_IN_HOOK`) stops recursion. Receipts and
  `hook.log` go to the plugin data dir (`$CLAUDE_PLUGIN_DATA`) or `~/.local/share/session-receipt/`.
  It needs `session-receipt` on PATH (`pip install -e .`) or `SESSION_RECEIPT_CMD`.

Try it without installing: `claude --plugin-dir integrations/claude-code/session-receipt`.
Remove it by dropping that flag (or `claude plugin uninstall` if you installed it). The plugin
never edits your settings or hooks. Hook tests: `python3 -m unittest discover -s integrations/claude-code/tests`.

Codex: no skill or hook is provided. Codex *reports* (above) are a separate capability from
any automatic Codex integration, which is not built.

## Evidence on real logs

Before release, the counts were reconciled on one machine's real logs (not included here):
an independent counter (dedup by message id + request id, keep the largest output, all
`projects/**/*.jsonl` including subagents) agreed with this tool field by field for a full day
of Claude Code usage, and direct counting of a Codex rollout's `token_count` events matched
ccusage's Codex figures. One lesson from that check: an early build "corrected" the sonnet-5-5
cache-read price from an out-of-date document; Anthropic's pricing page and the OpenRouter list
both give $0.10/MTok (0.05x input), so ccusage was right. Prices are now checked against a dated
snapshot (see above) rather than a hand-written table.

## Tests

```
python3 -m unittest discover -s tests -v
```

Tests use synthetic fixtures only (`examples/make_fixtures.py`, compact JSON because ccusage
silently ignores non-compact lines).
