@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (python run.py) else (py -3 run.py)
if errorlevel 1 (
  echo Python 실행에 실패했습니다. Python 3.10 이상 설치와 PATH를 확인하세요.
  pause
)
