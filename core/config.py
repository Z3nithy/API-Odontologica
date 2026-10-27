import os
from datetime import time
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./database.db")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
CLINIC_OPEN_TIME = time.fromisoformat(os.getenv("CLINIC_OPEN_TIME", "08:00"))
CLINIC_CLOSE_TIME = time.fromisoformat(os.getenv("CLINIC_CLOSE_TIME", "18:00"))

if not SECRET_KEY:
    raise RuntimeError("A variável SECRET_KEY precisa estar definida no ambiente.")