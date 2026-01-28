from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import get_db_connection, test_connection

app = FastAPI(title="Safemap API")

# Use absolute paths to ensure it works regardless of where the server is started
BASE_DIR = Path(__file__).resolve().parent

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/db-test")
async def db_test():
    """Test database connection"""
    success, result = test_connection()
    if success:
        return {
            "status": "connected",
            "message": "Supabase is connected! ✅",
            "postgres_version": result
        }
    else:
        return {
            "status": "error",
            "message": "Database connection failed",
            "error": result
        }

# ---- DIN KODE HER ----
# Legg til dine egne tabeller og endepunkter under her

