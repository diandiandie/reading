from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/reading?charset=utf8mb4",
)
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-this-secret-before-production")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads"))).resolve()
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "5"))

# CORS 允许的前端来源地址，多个用逗号分隔
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if origin.strip()
]
