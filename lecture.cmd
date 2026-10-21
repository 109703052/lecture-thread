@echo off
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
"%~dp0.venv\Scripts\python.exe" "%~dp0lecture_pipeline.py" %*
