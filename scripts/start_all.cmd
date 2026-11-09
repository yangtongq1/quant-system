@echo off
REM quant-system services launcher (dashboard + scheduler)
cd /d "%~dp0.."

REM kill old instances listening on 8765 (best effort)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>&1

start "quant-dashboard" /min cmd /c "python -m streamlit run web/app.py --server.port 8765 --server.headless true > logs\streamlit.log 2> logs\streamlit_err.log"
start "quant-scheduler" /min cmd /c "python scripts\scheduler.py > logs\scheduler.log 2>&1"

timeout /t 6 /nobreak >nul
curl -s -o nul -w "dashboard HTTP %%{http_code}\n" http://127.0.0.1:8765/
echo services started.
