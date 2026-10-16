import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ---------- Database ----------
DB_SERVER = os.getenv("DB_SERVER", r".\SQLEXPRESS")
DB_NAME = os.getenv("DB_NAME", "BIAssistant")
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
DB_TRUSTED = os.getenv("DB_TRUSTED_CONNECTION", "yes").lower() == "yes"
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")


def get_db_url() -> str:
    """SQLAlchemy URL for SQL Server. Never print this: it can contain a password."""
    parts = [
        f"DRIVER={{{DB_DRIVER}}}",
        f"SERVER={DB_SERVER}",
        f"DATABASE={DB_NAME}",
        "TrustServerCertificate=yes",
    ]
    if DB_TRUSTED:
        parts.append("Trusted_Connection=yes")
    else:
        parts += [f"UID={DB_USER}", f"PWD={DB_PASSWORD}"]
    return "mssql+pyodbc:///?odbc_connect=" + quote_plus(";".join(parts))


# ---------- LLM ----------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()   # gemini | openai | anthropic
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite").strip()
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", "30"))

# ---------- Upload rules ----------
ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))

# ---------- Schema ----------
REQUIRED_COLUMNS = ["InvoiceNo", "StockCode", "Quantity", "InvoiceDate", "UnitPrice"]
OPTIONAL_COLUMNS = ["Description", "CustomerID", "Country"]
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

# ---------- Business rules (single source of truth) ----------
CANCELLATION_PREFIX = "C"   # invoices starting with C are cancellations
SEVERITIES = ("INFO", "WARNING", "ERROR")