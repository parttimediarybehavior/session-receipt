---
name: receipt
description: Make a Session Receipt (a nutrition-label style usage receipt) for the current Claude Code session or a given day. Use when the user asks "how much did this session use", "show me a receipt", "token/cost receipt", or "what did today cost".
argument-hint: "[session|today|YYYY-MM-DD] [--env]"
allowed-tools: Bash(session-receipt:*)
---

# Session Receipt

Run the local `session-receipt` CLI. Never recount tokens yourself; never estimate numbers it did not print. It makes no model calls.

Current session id: `${CLAUDE_SESSION_ID}`

1. Choose the command from `$ARGUMENTS`:
   - empty or `session`: `session-receipt session --id ${CLAUDE_SESSION_ID} --out ./receipts`
   - `today`: `session-receipt daily --date "$(date +%F)" --out ./receipts`
   - a date `YYYY-MM-DD`: `session-receipt daily --date <date> --out ./receipts`
   - pass `--env` through only if the user asked for it (environmental scenarios are illustrative, not measurements).
2. If `session-receipt` is not on PATH, say so and point to the project's README install steps; do not improvise.
3. Report the file paths it printed and the headline lines exactly as printed. Say plainly:
   - a receipt for the *current* session is PROVISIONAL: it cannot include the tokens of this reply or anything after it;
   - cost is an API list-price equivalent, not a subscription charge;
   - any model shown as "unknown" price is excluded from the cost total.
