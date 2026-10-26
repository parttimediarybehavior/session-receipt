# Changelog

Plugin users get an update only when the version changes. See [Releasing](README.md#releasing).

## 1.0.0 (2026-10-26)

The first versioned release.

### What it does

- Makes session and daily receipts for Claude Code from your local logs. A receipt shows the
  tokens recorded per model, an API list-price equivalent cost, and where the numbers came from.
  Codex receipts are experimental.
- Runs as plain local code. It makes no model calls, and a receipt makes no network calls.
- Writes HTML, SVG and JSON. Receipts leave out paths, usernames and raw session IDs unless you
  pass `--private`.

### New in this release

- Installs as a Claude Code plugin from this repository, or with one line, with no `pip install`
  (#7).
- `session-receipt doctor` checks Python, the time zone database and ccusage, and prints the fix
  for each problem (#7).
- Supports Windows, including the optional SessionEnd hook (#3).
- `--tz` defaults to `SESSION_RECEIPT_TZ`, then `TZ`, then the system time zone (#6).
- `update-prices` builds the new price files in a staging folder first, and puts the old ones
  back if a step fails (#4).
- A Claude receipt with no priced model shows an unknown total, not $0. Codex receipts check
  ccusage's token counts against the logs' own records (#5).
- The plugin has a version, an icon and a homepage (#10).

### Tested on

- Linux x64 and Windows x64. On Windows, a real install from the marketplace, the
  `/session-receipt:receipt` skill and the SessionEnd hook all worked.
- Not tested yet: macOS, and `/session-receipt:receipt today` on Windows.
