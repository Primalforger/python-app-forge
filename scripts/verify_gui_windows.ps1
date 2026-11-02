$ErrorActionPreference = "Stop"

$stdoutPath = Join-Path $env:RUNNER_TEMP ("verify-gui-" + [guid]::NewGuid() + ".stdout.log")
$stderrPath = Join-Path $env:RUNNER_TEMP ("verify-gui-" + [guid]::NewGuid() + ".stderr.log")
$process = Start-Process -FilePath "python" -ArgumentList @("scripts/verify_gui.py") -PassThru -NoNewWindow -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath

# Bound process teardown so a lingering Qt/native thread cannot leave CI running indefinitely.
$finished = $process.WaitForExit(90000)
$stdout = if (Test-Path $stdoutPath) { Get-Content -Raw $stdoutPath } else { "" }
$stderr = if (Test-Path $stderrPath) { Get-Content -Raw $stderrPath } else { "" }

if ($stdout) { Write-Output $stdout.TrimEnd() }
if ($stderr) { [Console]::Error.WriteLine($stderr.TrimEnd()) }

if ($finished) {
    $process.Refresh()
    if ($process.ExitCode -ne 0) {
        Write-Error "Real-Qt verifier exited with code $($process.ExitCode)."
        exit $process.ExitCode
    }
    if ($stdout -notmatch '(?m)^RESULT:\s+\d+ GUI tests passed under real Qt \(offscreen\)\.\s*$') {
        Write-Error "Verifier exited successfully without its explicit real-Qt pass verdict."
        exit 1
    }
    Write-Output "Windows real-Qt verifier exited cleanly."
    exit 0
}

$passed = $stdout -match '(?m)^RESULT:\s+\d+ GUI tests passed under real Qt \(offscreen\)\.\s*$'
Write-Warning "The Python/Qt process did not exit within 90 seconds after the GUI suite."
# Kill the entire process tree so no Qt child or native helper can keep the step alive.
& taskkill.exe /PID $process.Id /T /F | Out-Null

if ($passed) {
    Write-Warning "All GUI tests reported PASS; terminated the lingering process tree."
    exit 0
}

Write-Error "The verifier timed out before producing an explicit GUI pass verdict."
exit 1
