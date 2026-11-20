# Run the backend test suite with the project's virtualenv.
#   ./tools/run_tests.ps1                       full offline suite
#   ./tools/run_tests.ps1 tests/test_x.py -k y  any pytest arguments
# The full run's output is also written to tests/out/last_run.txt.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
Set-Location $root
$out = Join-Path $root "tests\out\last_run.txt"
New-Item -ItemType Directory -Force (Split-Path -Parent $out) | Out-Null
& $python -m pytest -q -p no:cacheprovider --tb=short @args 2>&1 | Tee-Object -FilePath $out
exit $LASTEXITCODE
