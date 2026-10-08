@echo off
title Sunlit BI - server (close this window to stop the app)
cd /d "%~dp0"

rem Start the dashboard server in a minimised window
start "Sunlit BI server" /min python -m streamlit run Executive_Dashboard.py --server.headless true

rem Wait a few seconds for the server to start
timeout /t 6 /nobreak >nul

rem Open the dashboard in its own app-style window (no tabs, no address bar)
start msedge --app=http://localhost:8501

exit
