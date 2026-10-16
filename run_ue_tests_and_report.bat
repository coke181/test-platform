@echo off
setlocal

rem ============================================================
rem  Blaster UE automation tests: run -> locate -> convert -> push
rem  Usage:
rem    run_ue_tests_and_report.bat [test_filter] [project] [run_name]
rem  Example:
rem    run_ue_tests_and_report.bat Blaster blaster ue-automation
rem ============================================================

set "TEST_FILTER=%~1"
if "%TEST_FILTER%"=="" set "TEST_FILTER=Blaster"
set "PROJECT_NAME=%~2"
if "%PROJECT_NAME%"=="" set "PROJECT_NAME=blaster"
set "RUN_NAME=%~3"
if "%RUN_NAME%"=="" set "RUN_NAME=ue-automation"

if defined UE_EDITOR_CMD (
    set "UE_EDITOR=%UE_EDITOR_CMD%"
) else (
    set "UE_EDITOR=D:\UE_resources\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
)
if defined BLASTER_UPROJECT (
    set "UPROJECT=%BLASTER_UPROJECT%"
) else (
    set "UPROJECT=D:\ueproject\Blaster\Blaster\Blaster.uproject"
)
set "REPORT_DIR=D:\ueproject\Blaster\Blaster\Saved\AutomationReports"
set "LOG_DIR=D:\ueproject\Blaster\Blaster\Saved\Logs"
set "PLATFORM_DIR=D:\code\test-platform"

if not exist "%UE_EDITOR%" (
    echo [ERROR] UnrealEditor-Cmd.exe not found: %UE_EDITOR%
    echo Set UE_EDITOR_CMD to the engine editor path.
    exit /b 1
)
if not exist "%UPROJECT%" (
    echo [ERROR] Project file not found: %UPROJECT%
    echo Set BLASTER_UPROJECT to the .uproject path.
    exit /b 1
)
if not exist "%PLATFORM_DIR%\ue_to_junit.py" (
    echo [ERROR] Converter not found: %PLATFORM_DIR%\ue_to_junit.py
    exit /b 1
)

echo.
echo ============================================================
echo [1/3] Running UE automation tests, filter: %TEST_FILTER%
echo ============================================================
"%UE_EDITOR%" "%UPROJECT%" -unattended -NullRHI -NoSplash -NoPause -ExecCmds="Automation RunTests %TEST_FILTER%; Quit" -TestExit="Automation Test Queue Empty" -ReportOutputPath="%REPORT_DIR%"

echo.
echo ============================================================
echo [2/3] Locating newest AutomationReports\index.json and log
echo ============================================================
set "REPORT_JSON="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%REPORT_DIR%' -Recurse -Filter index.json -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName"`) do set "REPORT_JSON=%%i"

if "%REPORT_JSON%"=="" (
    echo [ERROR] index.json not found. Check the UE report output path.
    exit /b 1
)
echo Report: %REPORT_JSON%

set "LOG_FILE="
for /f "usebackq delims=" %%j in (`powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%LOG_DIR%' -Filter *.log -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName"`) do set "LOG_FILE=%%j"
if "%LOG_FILE%"=="" (
    echo [WARN] No log found in %LOG_DIR%, evidence will be skipped.
) else (
    echo Log: %LOG_FILE%
)

echo.
echo ============================================================
echo [3/3] Converting to JUnit XML and pushing to platform
echo ============================================================
cd /d "%PLATFORM_DIR%"
if "%LOG_FILE%"=="" (
    python ue_to_junit.py "%REPORT_JSON%" --project %PROJECT_NAME% --name "%RUN_NAME%" --push --api http://127.0.0.1:5000
) else (
    python ue_to_junit.py "%REPORT_JSON%" --project %PROJECT_NAME% --name "%RUN_NAME%" --push --api http://127.0.0.1:5000 --evidence "%LOG_FILE%"
)
if errorlevel 1 (
    echo.
    echo [WARN] Push failed. Start the platform first:
    echo        cd /d %PLATFORM_DIR%
    echo        python run.py
    echo        Then rerun this script, or push manually:
    echo        python ue_to_junit.py "%REPORT_JSON%" --project %PROJECT_NAME% --name "%RUN_NAME%" --push
)

echo.
echo Done.
endlocal