# OI Dominance project handoff

## Purpose

Publish a mobile-friendly, public OI dominance chart that updates every day without relying on the user's computer.

## Current architecture

- GitHub Actions starts daily at 00:20 UTC (08:20 Asia/Shanghai).
- `outputs/oi-dominance/daily-update.ps1` refreshes the latest completed UTC day from Coinalyze and Binance Data Vision.
- `.github/workflows/daily-update.yml` validates freshness and continuity, then commits refreshed source outputs.
- The data commit triggers `.github/workflows/pages.yml`, which rebuilds the downloadable Excel workbook and static GitHub Pages payload.
- Splitting update and publication lets the initial push publish existing validated data immediately and preserves the last good site when an API update fails.

## Required GitHub configuration

1. Add an Actions repository secret named `COINALYZE_API_KEY`.
2. In Settings > Pages, select GitHub Actions as the source.
3. Allow Actions to write repository contents if the repository or organization overrides workflow permissions.

## Local run

```powershell
./outputs/oi-dominance/daily-update.ps1
python ./outputs/oi-dominance/export-xlsx.py
node ./outputs/oi-dominance/publish-site.mjs
```

Local Windows unattended runs may use the DPAPI helper. GitHub Actions must use the encrypted repository secret and never the DPAPI file.

## Data outputs committed to the repository

- `outputs/oi-dominance/data/dominance-cleaned.csv`
- `outputs/oi-dominance/data/summary.json`
- `outputs/oi-dominance/data/excluded-underlyings.csv`
- `outputs/oi-dominance/data/dominance-2021plus.csv`
- `outputs/oi-dominance/data/dominance-2021plus-summary.json`
- `outputs/oi-dominance/data/dominance-2021plus.html`
- `outputs/oi-dominance/data/daily-update-status.json`
- `outputs/oi-dominance/data/btc-price/btc-price-daily.csv`

## Recovery

- A failed run leaves the published site unchanged.
- Use Actions > Daily OI update and Pages deployment > Run workflow to retry.
- Coinalyze responses are rate-limited to 40 symbols per minute and the updater honors `Retry-After`; a complete run normally takes about two hours.

