param(
  [ValidateRange(2, 14)]
  [int]$CorrectionDays = 3,
  [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'
$dataDir = Join-Path $PSScriptRoot 'data'
$summaryPath = Join-Path $dataDir 'summary.json'
$pricePath = Join-Path $dataDir 'btc-price\btc-price-daily.csv'
$credentialPath = $null
if ($IsWindows -and $env:LOCALAPPDATA) {
  $credentialPath = Join-Path $env:LOCALAPPDATA 'OI-Dominance\coinalyze-key.dpapi'
}
$targetDate = [DateTime]::UtcNow.Date.AddDays(-1)

if (-not (Test-Path -LiteralPath $summaryPath)) {
  throw "Missing existing Coinalyze summary: $summaryPath"
}

$summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
$latestDate = [DateTime]::ParseExact([string]$summary.latest.date, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
$refreshFrom = $latestDate.AddDays(-($CorrectionDays - 1))
if ($refreshFrom -gt $targetDate) { $refreshFrom = $targetDate.AddDays(-($CorrectionDays - 1)) }
$fromText = $refreshFrom.ToString('yyyy-MM-dd')
$toText = $targetDate.ToString('yyyy-MM-dd')

$ownsKey = $false
$apiKeyPtr = [IntPtr]::Zero
if (-not $env:COINALYZE_API_KEY) {
  if ($credentialPath -and (Test-Path -LiteralPath $credentialPath)) {
    $secureKey = ConvertTo-SecureString -String ((Get-Content -LiteralPath $credentialPath -Raw).Trim())
  } elseif ($NonInteractive) {
    throw 'COINALYZE_API_KEY is missing. Configure it as an encrypted environment secret.'
  } else {
    $secureKey = Read-Host 'Coinalyze API key' -AsSecureString
  }
  $apiKeyPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
  $env:COINALYZE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($apiKeyPtr)
  $ownsKey = $true
}

try {
  Write-Host "Refreshing Coinalyze $fromText to $toText (about two hours at 40 symbols/min)..."
  & node (Join-Path $PSScriptRoot 'oi-dominance.mjs') "--from=$fromText" "--to=$toText" '--merge-existing'
  if ($LASTEXITCODE -ne 0) { throw "Coinalyze update failed with exit code $LASTEXITCODE" }

  $python = Get-Command python -ErrorAction SilentlyContinue
  if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
  if (-not $python) { throw 'Python was not found on PATH.' }

  Write-Host "Refreshing BTC price $fromText to $toText..."
  & $python.Source (Join-Path $PSScriptRoot 'btc-price-backfill.py') "--from=$fromText" "--to=$toText" '--merge-existing'
  if ($LASTEXITCODE -ne 0) { throw "BTC price update failed with exit code $LASTEXITCODE" }

  & node (Join-Path $PSScriptRoot 'combine-2021plus.mjs')
  if ($LASTEXITCODE -ne 0) { throw "Combined output failed with exit code $LASTEXITCODE" }

  $combinedSummary = Get-Content -LiteralPath (Join-Path $dataDir 'dominance-2021plus-summary.json') -Raw | ConvertFrom-Json
  if ([string]$combinedSummary.to -ne $toText) {
    throw "Freshness validation failed: expected latest observation $toText, received $($combinedSummary.to)"
  }
  if ([int]$combinedSummary.validation.date_gap_count -ne 0 -or
      [int]$combinedSummary.validation.negative_oi_row_count -ne 0 -or
      [int]$combinedSummary.validation.missing_btc_price_row_count -ne 0) {
    throw 'Combined output failed integrity validation.'
  }
  $status = [ordered]@{
    completed_at = [DateTime]::UtcNow.ToString('o')
    target_date = $toText
    latest_observation = [string]$combinedSummary.to
    observations = [int]$combinedSummary.observations
    date_gap_count = [int]$combinedSummary.validation.date_gap_count
    missing_btc_price_row_count = [int]$combinedSummary.validation.missing_btc_price_row_count
  }
  $status | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dataDir 'daily-update-status.json') -Encoding UTF8
  $status | ConvertTo-Json
} finally {
  if ($ownsKey) {
    Remove-Item Env:COINALYZE_API_KEY -ErrorAction SilentlyContinue
    if ($apiKeyPtr -ne [IntPtr]::Zero) {
      [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($apiKeyPtr)
    }
  }
}
