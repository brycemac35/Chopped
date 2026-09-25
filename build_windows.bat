@echo off
REM Builds dist\Chopped.exe (single file, no console window, with icon).
REM Needs Python 3.12 from python.org (the "py" launcher): py -3.12 --version
REM
REM Don't have Python? You don't need it: every push to GitHub builds the exe
REM for you (Actions tab -> latest "Windows exe" run -> Chopped-windows artifact).
setlocal
cd /d "%~dp0"

py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo !! Python 3.12 not found. Install it from python.org and tick "Add python.exe to PATH".
  exit /b 1
)

if not exist .venv (
  echo == creating virtual environment .venv
  py -3.12 -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat || goto :fail

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller==6.22.3
if errorlevel 1 (
  echo !! full requirements failed - retrying without miniupnpc ^(UPnP is optional^)
  python -m pip install pygame-ce==2.5.8 pyinstaller==6.22.3 || goto :fail
)

echo == drawing the icon ^(generated from the game's own sprite code^)
python tools\make_icon.py || goto :fail

python -m PyInstaller --noconfirm --clean Chopped.spec || goto :fail

echo == smoke test: headless selftest + a host and a client exe talking over UDP
python tools\smoke_exe.py dist\Chopped.exe
if errorlevel 1 (
  echo !! smoke test failed - logs are in dist\smoke-logs. The exe may still run; try launching it.
  exit /b 1
)
echo.
echo == Done: dist\Chopped.exe
echo    First launch: allow Chopped through Windows Firewall ^(Private networks^) so friends can join.
exit /b 0

:fail
echo !! build failed
exit /b 1
