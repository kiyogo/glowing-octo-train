@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title FB ACCOUNT FACTORY
cd /d "%~dp0"

REM ============================================================
REM  SETTINGS - edit these, save, double-click this file.
REM ============================================================
set "COUNT=5"                    REM how many accounts
set "WORKERS=1"                  REM parallel attempts
set "USE_TEMPMAIL=1"             REM 1 = temp-mail.org per account
set "EMAIL_DOMAIN=mail.mydomain.tld"   REM used only when USE_TEMPMAIL=0
set "SOLVER=none"                REM none, capsolver, 2captcha, anticaptcha, manual
set "SOLVER_KEY="                REM solver api key
set "HEADED=1"                   REM 1 = show the browser, needed for manual captcha
set "ALLOW_DIRECT=1"             REM 1 = run without proxies, expect rate limits
set "DELAY=20,55"                REM seconds between attempts, min,max
set "REPAIR=1"                   REM 1 = finish confirmation / checkpoint after each run
set "DRYRUN=0"                   REM 1 = fill the form but never submit
set "OUT=out"
REM ============================================================

echo.
echo  ============================================================
echo    FB ACCOUNT FACTORY
echo    accounts: !COUNT!   workers: !WORKERS!   solver: !SOLVER!
echo    mail: temp-mail=!USE_TEMPMAIL!   headed: !HEADED!   dry-run: !DRYRUN!
echo  ============================================================
echo.

REM ---------- 0. sanity ----------
where python >nul 2>nul
if errorlevel 1 (
  echo [X] python is not in PATH. Install Python 3.10+ and tick "Add to PATH".
  goto :fail
)

echo [1/6] dependencies
python -c "import requests" >nul 2>nul || python -m pip install -q -r fbreg\requirements.txt
python -c "import playwright" >nul 2>nul || python -m pip install -q playwright
if errorlevel 1 (
  echo [X] pip install failed.
  goto :fail
)

echo [2/6] chromium
if not exist "%LOCALAPPDATA%\ms-playwright" (
  python -m playwright install chromium
) else (
  echo       present
)

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
set "OUTDIR=!OUT!\run_!STAMP!"
if not exist "!OUTDIR!" mkdir "!OUTDIR!"

REM ---------- proxies ----------
echo [3/6] proxies
set "HAVEPROXY=0"
if exist "fbreg\proxies.txt" (
  for /f "usebackq delims=" %%L in (`findstr /v /b /c:"#" "fbreg\proxies.txt" 2^>nul`) do (
    if not "%%L"=="" set "HAVEPROXY=1"
  )
)
set "PROXYARG="
if "!HAVEPROXY!"=="0" (
  if "!ALLOW_DIRECT!"=="1" (
    echo       none found - running direct
    set "PROXYARG=--direct"
  ) else (
    echo [X] fbreg\proxies.txt has no proxies and ALLOW_DIRECT=0
    goto :fail
  )
) else (
  python -m fbreg --check-proxies -p fbreg\proxies.txt
  set "PROXYARG=-p fbreg\proxies.txt"
)

REM ---------- args ----------
REM  headed with no solver means the human solves it - make that explicit
if /i "!SOLVER!"=="none" if "!HEADED!"=="1" set "SOLVER=manual"
set "SOLVERARG="
if /i not "!SOLVER!"=="none" (
  if /i not "!SOLVER!"=="manual" (
    if "!SOLVER_KEY!"=="" (
      echo       no solver key - falling back to manual captcha
      set "SOLVER=manual"
    )
  )
  set "SOLVERARG=--solver !SOLVER!"
  if not "!SOLVER_KEY!"=="" set "SOLVERARG=!SOLVERARG! --solver-key !SOLVER_KEY!"
)
set "HEADARG="
if "!HEADED!"=="1" set "HEADARG=--headed"

if "!USE_TEMPMAIL!"=="1" (
  set "MAILARG=--tempmail"
) else (
  set "MAILARG=-d !EMAIL_DOMAIN!"
)
set "DRYARG="
if "!DRYRUN!"=="1" set "DRYARG=--dry-run"

REM ---------- run ----------
echo [4/6] creating accounts
echo       out: !OUTDIR!
python -m fbreg -n !COUNT! -w !WORKERS! !MAILARG! !SOLVERARG! !HEADARG! !PROXYARG! --delay !DELAY! --out "!OUTDIR!" !DRYARG!
if errorlevel 1 echo       (run exited with code %errorlevel%)

REM ---------- repair ----------
set "SKIPREPAIR=0"
if "!REPAIR!"=="0" set "SKIPREPAIR=1"
if "!DRYRUN!"=="1" set "SKIPREPAIR=1"
echo.
echo [5/6] confirming and clearing checkpoints
if "!SKIPREPAIR!"=="1" (
  echo       skipped
) else (
  if exist "!OUTDIR!\cookies\*.mailbox.json" (
    for %%F in ("!OUTDIR!\cookies\*.mailbox.json") do (
      set "MBF=%%~fF"
      set "STA=!MBF:.mailbox.json=.json!"
      echo       %%~nxF
      python -m fbreg.repair --state "!STA!" --mailbox "!MBF!" !SOLVERARG! !HEADARG!
    )
  ) else (
    echo       nothing to repair
  )
)

echo.
echo [6/6] done
if exist "!OUTDIR!\accounts.txt" (
  echo  -------- accounts on file --------
  type "!OUTDIR!\accounts.txt"
  echo  ----------------------------------
) else (
  echo  no accounts created this run
)
echo  log: !OUTDIR!\attempts.log
echo.

echo Press any key to close.
pause >nul
exit /b 0

:fail
echo.
echo  STOPPED - read the message above.
pause >nul
exit /b 1
