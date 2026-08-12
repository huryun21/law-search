@echo off
setlocal
cd /d "%~dp0"

if not exist "config.local.toml" goto missing_config

if exist ".venv\Scripts\python.exe" goto check_install
where py >nul 2>nul
if errorlevel 1 goto missing_python
py -3.12 -m venv .venv
if errorlevel 1 goto venv_failed

:check_install
".venv\Scripts\python.exe" -c "import lawsearch, streamlit, httpx" >nul 2>nul
if not errorlevel 1 goto launch
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto install_failed

:launch
".venv\Scripts\python.exe" -m streamlit run src\lawsearch\app.py --server.address 127.0.0.1 --server.headless false
if errorlevel 1 goto launch_failed
exit /b 0

:missing_config
powershell -NoProfile -EncodedCommand VwByAGkAdABlAC0ASABvAHMAdAAgACcAWwAkxli5XQAgAGMAbwBuAGYAaQBnAC4AbABvAGMAYQBsAC4AdABvAG0AbAB0xyAAxsW1wsiy5LIuACAACMYcyCAADNN8x0THIAD1vKzAXNUgAKS0IABBAFAASQAgAKTQIAAM03zHIAC9rFy4fLkgACTBFchY1TjBlMYuACcA
pause
exit /b 1

:missing_python
powershell -NoProfile -EncodedCommand VwByAGkAdABlAC0ASABvAHMAdAAgACcAWwAkxli5XQAgAFAAeQB0AGgAbwBuACAA5MKJ1TCuIABwAHkAfLkgAD7MwMkgALu6iNW1wsiy5LIuACAAUAB5AHQAaABvAG4AIAAzAC4AMQAyAHy5IAAkwVjOXNUgAKS0IADkstzCIADkwonVWNU4wZTGLgAnAA==
pause
exit /b 1

:venv_failed
powershell -NoProfile -EncodedCommand VwByAGkAdABlAC0ASABvAHMAdAAgACcAWwAkxli5XQAgAFAAeQB0AGgAbwBuACAAMwAuADEAMgAgAACswcBY1r2sIADdwDHB0MUgAOTCKNOI1bXCyLLksi4AIAAkwVjOIADBwNzQfLkgAFXWeMdY1TjBlMYuACcA
pause
exit /b 1

:install_failed
powershell -NoProfile -EncodedCommand VwByAGkAdABlAC0ASABvAHMAdAAgACcAWwAkxli5XQAgAHHFIAAkwVjO0MUgAOTCKNOI1bXCyLLksi4AIAB4xzDRN7EgAPDFsKz8rCAAcABpAHAAIAAkxli5fLkgAFXWeMdY1TjBlMYuACcA
pause
exit /b 1

:launch_failed
powershell -NoProfile -EncodedCommand VwByAGkAdABlAC0ASABvAHMAdAAgACcAWwAkxli5XQAgAHHFIADkwonVdMcgABHJ6LIYtMjFtcLIsuSyLgAgAATHIAAkxli5QMYgAGMAbwBuAGYAaQBnAC4AbABvAGMAYQBsAC4AdABvAG0AbAAgACTBFchExyAAVdZ4x1jVOMGUxi4AJwA=
pause
exit /b 1
