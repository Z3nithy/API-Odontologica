from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import CORS_ORIGINS
from database import Base, engine
from models import (
    Appointment,
    ClinicalDocument,
    ClinicalDocumentAudit,
    Clinic,
    DentalChartEntry,
    NotificationPreference,
    Patient,
    TreatmentPlan,
    TreatmentPlanAudit,
    TreatmentPlanProcedure,
    UserInvitation,
    UserManagementAudit,
    UserPreference,
    User,
)
from routes.auth import router as auth_router
from routes.dentist import router as dentist_router
from routes.manager_users import router as manager_users_router
from routes.manager_productivity import router as manager_productivity_router
from routes.manager_patients import router as manager_patients_router
from routes.reception import router as reception_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Zen API",
    description="API de autenticação e operações da clínica odontológica.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_router)
app.include_router(manager_users_router)
app.include_router(manager_productivity_router)
app.include_router(manager_patients_router)
app.include_router(reception_router)
app.include_router(dentist_router)


@app.get("/api/health", tags=["Sistema"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", port=8000, reload=True)
