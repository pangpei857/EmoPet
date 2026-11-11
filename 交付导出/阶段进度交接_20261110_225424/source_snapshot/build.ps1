$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$petPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $petPython)) { throw 'Create .venv and install requirements-dev.txt first.' }
& $petPython -m PyInstaller --noconfirm --distpath dist --workpath build Momo.spec
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
Write-Output 'Ready: dist/Momo/Momo.exe. Share the whole Momo folder.'

