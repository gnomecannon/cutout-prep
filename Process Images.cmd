@echo off
setlocal
set "PROCESSOR_PYTHON=%CUTOUT_PREP_PYTHON%"
if defined PROCESSOR_PYTHON goto configured
if exist "%~dp0.venv\Scripts\python.exe" set "PROCESSOR_PYTHON=%~dp0.venv\Scripts\python.exe"
if defined PROCESSOR_PYTHON goto configured
where py >nul 2>nul
if errorlevel 1 goto plain
py -3 -m cutout_prep %*
goto finished
:plain
python -m cutout_prep %*
goto finished
:configured
"%PROCESSOR_PYTHON%" -m cutout_prep %*
:finished
set "PROCESS_RESULT=%ERRORLEVEL%"
echo.
if not defined CUTOUT_PREP_NO_PAUSE pause
exit /b %PROCESS_RESULT%
