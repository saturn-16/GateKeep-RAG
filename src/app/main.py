from fastapi import FastAPI

from app.config import get_settings
from app.api import admin, audit, auth, documents, query

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.include_router(auth.router)
app.include_router(query.router)
app.include_router(documents.router)
app.include_router(audit.router)
app.include_router(admin.router)


@app.get("/healthz", tags=["health"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
def readyz() -> dict[str, str]:
    return {"status": "ready"}
