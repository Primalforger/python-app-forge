$ErrorActionPreference = "Stop"

$stdoutPath = Join-Path $env:RUNNER_TEMP ("verify-gui-" + [guid]::NewGuid() + ".stdout.log")
$stderrPath = Join-Path $env:RUNNER_TEMP ("verify-gui-" + [guid]::NewGuid() + ".stderr.log")
$process = Start-Process -FilePath "python" -ArgumentList @("scripts/verify_gui.py") -PassThru -NoNewWindow -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath

# Bound process teardown so a lingering Qt/native thread cannot leave CI running indefinitely.
$finished = $process.WaitForExit(180000)
if (-not $finished) {
    # The child can exit between WaitForExit timing out and taskkill running.
    # Give that race a short grace period, then refresh before inspecting ExitCode.
    $finished = $process.WaitForExit(5000)
}
$process.Refresh()
$stdout = if (Test-Path $stdoutPath) { Get-Content -Raw $stdoutPath } else { "" }
$stderr = if (Test-Path $stderrPath) { Get-Content -Raw $stderrPath } else { "" }

if ($stdout) { Write-Output $stdout.TrimEnd() }
if ($stderr) { [Console]::Error.WriteLine($stderr.TrimEnd()) }

if ($finished -or $process.HasExited) {
    if ($process.ExitCode -ne 0) {
        Write-Error "Real-Qt verifier exited with code $($process.ExitCode)."
        exit 1
    }
    if ($stdout -notmatch '(?m)^RESULT:\s+\d+ GUI tests passed under real Qt \(offscreen\)\.\s*$') {
        Write-Error "Verifier exited successfully without its explicit real-Qt pass verdict."
        exit 1
    }
    Write-Output "Windows real-Qt verifier exited cleanly."
    exit 0
}

$passed = $stdout -match '(?m)^RESULT:\s+\d+ GUI tests passed under real Qt \(offscreen\)\.\s*$'
Write-Warning "The Python/Qt process did not exit within 185 seconds after the GUI suite."
# Kill the entire process tree so no Qt child or native helper can keep CI running indefinitely.
& taskkill.exe /PID $process.Id /T /F | Out-Null
$process.Refresh()

if ($passed) {
    Write-Warning "All GUI tests reported PASS; terminated the lingering process tree."
    exit 0
}

Write-Error "The verifier timed out before producing an explicit GUI pass verdict."
exit 1
