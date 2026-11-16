<#
.SYNOPSIS
    Build "LMU Telemetry.exe" and check that it actually starts.

.DESCRIPTION
    1. Installs the build dependencies (requirements-build.txt) into .venv.
    2. Runs PyInstaller on packaging\lmu_telemetry.spec.
    3. Smoke-tests the result: imports the demo session into a throwaway data
       folder, launches the .exe with --smoke-test and fails unless it opened
       the lap and exited cleanly. A build that only *compiles* proves nothing.

    Output: dist\LMU Telemetry\LMU Telemetry.exe (copy the whole folder).
    User data is not in it: it lives in %USERPROFILE%\.lmu-telemetry.

.PARAMETER Shortcut
    Also put a "LMU Telemetry" shortcut on the desktop.

.EXAMPLE
    .\scripts\build_exe.ps1
    .\scripts\build_exe.ps1 -Shortcut
#>
param([switch]$Shortcut)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$name = "LMU Telemetry"
$exe = Join-Path $root "dist\$name\$name.exe"

if (-not (Test-Path $python)) {
    throw "Ambiente virtual não encontrado em $python. Crie-o e instale requirements.txt primeiro."
}
# Relative paths below (data\demo) are the project's.
Set-Location $root

Write-Host "==> Dependências de build"
& $python -m pip install --quiet --disable-pip-version-check -r (Join-Path $root "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { throw "pip falhou" }

Write-Host "==> PyInstaller"
& $python -m PyInstaller (Join-Path $root "packaging\lmu_telemetry.spec") `
    --noconfirm --clean `
    --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }

Write-Host "==> Teste de fumaça"
$scratch = Join-Path ([System.IO.Path]::GetTempPath()) ("lmu-telemetry-smoke-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $scratch | Out-Null
try {
    $env:LMU_TELEMETRY_DATA_DIR = $scratch
    & $python -c "from pathlib import Path; from lmu_telemetry.infrastructure.storage import importer; importer.import_session_file(sorted(Path('data/demo').glob('*.duckdb'))[0])"
    if ($LASTEXITCODE -ne 0) { throw "não foi possível importar o demo para o teste" }

    $process = Start-Process -FilePath $exe -ArgumentList "--smoke-test" -PassThru -Wait
    $log = Get-Content (Join-Path $scratch "lmu-telemetry.log") -Raw
    if ($process.ExitCode -ne 0 -or $log -notmatch "Smoke test passed" -or $log -notmatch "Loaded .*: ") {
        Write-Host $log
        throw "O .exe não abriu a volta do demo (código $($process.ExitCode))."
    }
}
finally {
    Remove-Item Env:\LMU_TELEMETRY_DATA_DIR -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $scratch -ErrorAction SilentlyContinue
}

$size = (Get-ChildItem (Split-Path $exe) -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("==> Pronto: {0} ({1:N0} MB na pasta)" -f $exe, $size)

if ($Shortcut) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop "$name.lnk"))
    $link.TargetPath = $exe
    $link.WorkingDirectory = Split-Path $exe
    $link.IconLocation = "$exe,0"
    $link.Save()
    Write-Host "==> Atalho criado na área de trabalho"
}
