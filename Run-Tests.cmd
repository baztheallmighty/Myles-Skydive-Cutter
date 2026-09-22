@echo off
setlocal
cd /d "%~dp0"
rem  Run-Tests            fast checks: the app's logic and process, seconds, no GPU
rem  Run-Tests ui         adds the real window on the demo videos (needs the staged package)
rem  Run-Tests full       adds the end-to-end run on real footage and the install check
set "MODE=%~1"
if "%MODE%"=="" set "MODE=fast"
rem  The Python to test with: SC_PYTHON if set, else this folder's .venv, else python on PATH.
if not "%SC_PYTHON%"=="" (set "PY=%SC_PYTHON%") else (set "PY=.venv\Scripts\python.exe")
if not exist "%PY%" set "PY=python"

echo == fast: app logic and process ==
"%PY%" -m pytest tests\app -q
if errorlevel 1 goto failed
if /i "%MODE%"=="fast" goto done

rem  The staged package to test. Set SC_PACKAGE to use another, e.g. an installed copy from the install test.
if "%SC_PACKAGE%"=="" (set "PACKAGE=release\dist\Skydive-Cutter-2.4.0") else (set "PACKAGE=%SC_PACKAGE%")
rem  Whichever runtime that package installed: the GPU builds first, then the processor build.
set "RUNTIME="
for %%R in (cu128 cu118 cpu) do if not defined RUNTIME if exist "%PACKAGE%\.runtime\%%R\python.exe" set "RUNTIME=%%R"
if not defined RUNTIME (
  echo Staged package with a runtime not found at %PACKAGE%; skipping the window and package checks.
  goto done
)
set "DEVICE=cuda"
if "%RUNTIME%"=="cpu" set "DEVICE=cpu"
echo.
echo == window: the real interface on the demo videos ==
pushd "%PACKAGE%"
".runtime\%RUNTIME%\python.exe" -s -B ..\..\tests\ui_test.py --keep-demo --demo "%CD%\..\..\..\build\demo360"
set "UI=%ERRORLEVEL%"
popd
if not "%UI%"=="0" goto failed
if /i "%MODE%"=="ui" goto done

echo.
echo == package: install check ==
pushd "%PACKAGE%"
".runtime\%RUNTIME%\python.exe" -s -B verify_install.py --device %DEVICE% >nul
set "INSTALL=%ERRORLEVEL%"
popd
if not "%INSTALL%"=="0" goto failed

:done
echo.
echo All requested checks passed.
exit /b 0

:failed
echo.
echo CHECKS FAILED.
exit /b 1
