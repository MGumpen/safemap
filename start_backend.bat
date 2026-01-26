@echo off
echo Starting SafeMap Backend...
set DATABASE_URL=postgresql://postgres:safemap@localhost:5432/postgres
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
pause
