@echo off
echo ========================================
echo SafeMap Setup and Run
echo ========================================

echo.
echo [1/4] Installing Python packages...
python -m pip install requests psycopg2-binary uvicorn fastapi pydantic pydantic-settings pyyaml --quiet

echo.
echo [2/4] Importing POI data from OpenStreetMap...
python scripts\check_and_ingest.py

echo.
echo [3/4] Starting backend server...
set DATABASE_URL=postgresql://postgres:safemap@localhost:5432/postgres
start "SafeMap Backend" cmd /k "cd /d %~dp0 && set DATABASE_URL=postgresql://postgres:safemap@localhost:5432/postgres && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload"

echo.
echo [4/4] Starting frontend server...
start "SafeMap Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo ========================================
echo SafeMap is starting!
echo Backend: http://localhost:8000
echo Frontend: http://localhost:5173
echo ========================================
pause
