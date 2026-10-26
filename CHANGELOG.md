# Changelog

## 1.0.0 (2026-10-26)

The first release. Session Receipt turns your Claude Code usage logs into a receipt. The receipt shows recorded tokens, a cost at API list prices, and where each number came from. Codex support is experimental. The tool makes no model calls, and receipts make no network calls.

### Receipts

- Make a receipt for one session or one day, as HTML, SVG and JSON.
- See tokens per model: input, output, cache writes and cache reads.
- See the cost at API list prices. This is not what a subscription plan charges.
- If a model has no known price, the receipt leaves it out of the total and marks the total as partial.
- If a total is not known, the receipt says so instead of showing zero.
- Each receipt names its sources: the ccusage version, the price list date and check status, and the time zone.
- Optional environmental scenarios, clearly marked as illustrations, not measurements.
- `demo` builds example receipts from synthetic logs, so you can try the tool with no real usage.

### Install and setup

- Install as a Claude Code plugin with one command, or clone the repository and run `npm ci`. You do not need `pip install`.
- The plugin installs a pinned copy of ccusage 20.0.38.
- `/session-receipt:receipt` makes a receipt from inside Claude Code.
- Optional: a SessionEnd hook writes a receipt automatically when a session ends.
- `session-receipt doctor` checks Python, the time zone database and ccusage, and prints the exact fix for each problem.

### Windows

- Runs on Windows with the native ccusage build and the `tzdata` package.
- The hook runs through `node` with no shell, so it works under PowerShell.
- The hook falls back from `python3` to `python` to `py -3`.
- The hook accepts input that starts with a byte-order mark.
- `doctor` prints commands that work in PowerShell.
- The skill gives PowerShell forms of its commands and pre-approves them.

### Time zones

- The default time zone comes from `SESSION_RECEIPT_TZ`, then `TZ`, then the system setting, then UTC.
- An unknown time zone gives an error that names where the bad value came from.

### Prices

- Prices come from a dated snapshot that the tool checks against a published price list.
- `update-prices` refreshes the snapshot only when you run it. It checks all the new price files before replacing any, and it rolls back if it is interrupted.

### Codex (experimental)

- Matches a session ID to its log on any operating system.
- Checks token counts and reports every kind of gap without crashing.
- Describes subagent usage accurately.

### Tests and CI

- Tests run on Ubuntu and Windows in CI.
- The test suite no longer leaves files open.
