@echo off
setlocal
set "APP_EXIT=1"
pushd "%~dp0"
if errorlevel 1 goto folder_error
if not exist "app.py" goto missing_app

py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto run_py

python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto run_python

echo Python 3.10 or newer was not found.
echo Install Python, then double-click this file again.
goto finish

:run_py
py -3 app.py
set "APP_EXIT=%errorlevel%"
goto finish

:run_python
python app.py
set "APP_EXIT=%errorlevel%"
goto finish

:folder_error
echo Could not open the folder containing this launcher.
pause >nul
exit /b 1

:missing_app
echo app.py was not found next to this launcher.
echo Extract the full ZIP archive, then run the launcher from that folder.
goto finish

:finish
echo.
echo The quiz assistant has stopped. Press any key to close this window.
pause >nul
popd
exit /b %APP_EXIT%
