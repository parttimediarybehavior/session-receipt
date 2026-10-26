@echo off
rem Runs the Session Receipt CLI from this checkout on Windows, with no pip install. Uses the first
rem of python3, python and py -3 that is Python 3.10 or later (the same order as bin/session-receipt
rem and the hook), and puts the checkout first on sys.path in place of the working directory, so a
rem file in the current folder cannot shadow a module.
setlocal
for %%P in ("python3" "python" "py -3") do (
  %%~P -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && (set "SR_PY=%%~P" & goto run)
)
echo session-receipt: needs Python 3.10 or later (tried python3, python, py -3). Install it from https://www.python.org/downloads/ and try again. 1>&2
exit /b 1
:run
%SR_PY% -c "import sys; sys.path[0] = sys.argv.pop(1); sys.argv[0] = 'session-receipt'; from session_receipt.cli import main; sys.exit(main())" "%~dp0.." %*
exit /b %errorlevel%
