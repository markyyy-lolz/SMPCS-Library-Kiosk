$ErrorActionPreference = 'Stop'
$report = Join-Path $PWD 'dist/SCAN_REPORT.txt'
$heading = "SMPCS Library build scan`nUTC: $([DateTime]::UtcNow.ToString('o'))`n"
try { $status = Get-MpComputerStatus -ErrorAction Stop } catch {
    ($heading + "NOT SCANNED: Microsoft Defender is unavailable on this build runner. No clean-scan claim is made.") | Set-Content $report
    Write-Host (Get-Content $report -Raw)
    exit 0
}
if (-not $status.AMServiceEnabled -or -not $status.AntivirusEnabled) {
    ($heading + "NOT SCANNED: Microsoft Defender is not active on this build runner. No clean-scan claim is made.") | Set-Content $report
    Write-Host (Get-Content $report -Raw)
    exit 0
}
$scanner = Get-ChildItem "$env:ProgramData\Microsoft\Windows Defender\Platform\*\MpCmdRun.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
$scannerPath = if ($scanner) { $scanner.FullName } else { "$env:ProgramFiles\Windows Defender\MpCmdRun.exe" }
$output = & $scannerPath -Scan -ScanType 3 -File (Join-Path $PWD 'dist') -DisableRemediation 2>&1
$scanExit = $LASTEXITCODE
($heading + "Engine: $($status.AMEngineVersion)`nSignatures: $($status.AntivirusSignatureVersion)`nExit code: $scanExit`n" + ($output -join "`n")) | Set-Content $report
Write-Host (Get-Content $report -Raw)
if ($scanExit -ne 0) { throw 'Defender scan reported a detection or error. Release publishing is blocked; inspect the scan output.' }
Add-Content $report 'Defender returned success for this build scan. This does not guarantee acceptance by other antivirus products or future signatures.'
