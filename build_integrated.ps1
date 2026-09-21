$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$python = Join-Path $taskRoot '.build-venv\Scripts\python.exe'
# Generate the shipped text from the same instructions displayed by the app.
$help = & $python -c "from app_help import HELP_TEXT; import sys; sys.stdout.buffer.write(HELP_TEXT.encode('utf-8'))"
if ($LASTEXITCODE -ne 0) { throw 'Failed to generate help' }
Set-Content -LiteralPath (Join-Path $taskRoot '使用说明.txt') -Value $help -Encoding utf8
& $python -m PyInstaller --onefile --windowed --noupx --name BatteryDataTool_050 --distpath (Join-Path $taskRoot 'release_build') --workpath (Join-Path $taskRoot 'build\pyinstaller') --specpath (Join-Path $taskRoot 'build') --additional-hooks-dir $taskRoot --add-data ((Join-Path $taskRoot 'THIRD_PARTY_NOTICES.md') + ':.') --add-data ((Join-Path $taskRoot '许可证') + ':许可证') (Join-Path $taskRoot 'neware_app.py')
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Get-FileHash -LiteralPath (Join-Path $taskRoot 'release_build\BatteryDataTool_050.exe') -Algorithm SHA256
