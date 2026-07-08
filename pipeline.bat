@echo off
cd /d "%~dp0"
python content_pipeline.py %*
