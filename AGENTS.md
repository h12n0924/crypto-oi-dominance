# Project instructions

- Never commit API keys, credentials, local encrypted secrets, logs, caches, or run locks.
- Preserve the documented split methodology: 2021-12-01 through 2022-07-29 uses Binance + Bybit fixed venues; 2022-07-30 onward uses the cleaned Coinalyze current universe.
- A daily publication is valid only when the combined series has no date gaps, no missing BTC prices, no negative OI rows, and its latest observation equals the latest completed UTC day.
- Keep `project-handoff.md` and `docs/agent-context/decision-ledger.md` current when deployment or methodology changes.

