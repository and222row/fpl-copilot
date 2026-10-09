# Serve the app to a development build on a real phone, from anywhere.
#
#   npm run phone
#
# Starts a Cloudflare quick tunnel to the Expo dev server, prints the address
# to enter on the phone (Development servers -> Enter URL manually), then runs
# the dev server. Ctrl+C stops both. The address changes on every run.
#
# The app reads its settings (API URL, Supabase, RevenueCat test key) from
# mobile/.env. The backend is the deployed one on Render, so nothing else needs
# to run on this PC.

$ErrorActionPreference = 'Stop'

$cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cloudflared) { $cloudflared = 'C:\Program Files (x86)\cloudflared\cloudflared.exe' }
if (-not (Test-Path $cloudflared)) {
  throw 'cloudflared is not installed. Run: winget install --id Cloudflare.cloudflared'
}

Set-Location (Split-Path $PSScriptRoot -Parent)

$log = Join-Path $env:TEMP 'fplc-phone-tunnel.log'
Remove-Item $log -ErrorAction SilentlyContinue
# cloudflared writes everything, the address included, to stderr.
$tunnel = Start-Process $cloudflared `
  -ArgumentList 'tunnel', '--no-autoupdate', '--url', 'http://localhost:8081' `
  -RedirectStandardError $log -WindowStyle Hidden -PassThru

try {
  $url = $null
  for ($i = 0; $i -lt 60 -and -not $url; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $log) {
      $match = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
      if ($match) { $url = $match.Matches[0].Value }
    }
  }
  if (-not $url) { throw "No tunnel address after 60 seconds. Details: $log" }

  Write-Host ''
  Write-Host '  On the phone: open FPL Copilot -> Enter URL manually ->' -ForegroundColor Green
  Write-Host "  $url" -ForegroundColor Green
  Write-Host ''

  # Expo advertises this address to the phone instead of the PC's LAN address.
  $env:EXPO_PACKAGER_PROXY_URL = $url
  npx expo start --dev-client --port 8081
}
finally {
  Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
}
