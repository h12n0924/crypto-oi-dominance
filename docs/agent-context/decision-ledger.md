# Decision ledger

## 2026-09-24: Public GitHub Pages deployment

- The user approved public access.
- Use GitHub Actions as the long-running updater because the exact full-universe Coinalyze method takes roughly two hours.
- Use GitHub Pages for the static interactive chart and downloads.
- Keep the exact existing methodology. Do not silently replace it with a faster active-contract approximation.
- Schedule at 00:20 UTC, after the UTC daily candle closes and away from the top of the hour.
- Store `COINALYZE_API_KEY` only as an encrypted GitHub Actions secret.
- Publish only successful, fully validated updates. If freshness or integrity checks fail, retain the previous public site.

