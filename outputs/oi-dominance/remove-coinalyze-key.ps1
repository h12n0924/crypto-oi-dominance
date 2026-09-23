$credentialPath = Join-Path $env:LOCALAPPDATA 'OI-Dominance\coinalyze-key.dpapi'
if (Test-Path -LiteralPath $credentialPath) {
  Remove-Item -LiteralPath $credentialPath -Force
  Write-Output "Removed encrypted credential: $credentialPath"
} else {
  Write-Output 'No encrypted Coinalyze credential was found.'
}
