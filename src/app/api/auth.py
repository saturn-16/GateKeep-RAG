from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.state import authenticate, state
from app.api.dependencies import current_user
from app.api.runtime import get_runtime_db
from app.config import get_settings
from app.core.security import create_access_token
from app.db.repository import append_audit, authenticate_user, load_user
from app.core.rate_limit import DatabaseRateLimiter

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


def issue_token(user: object) -> dict[str, str]:
    return {"access_token": create_access_token({"sub": user.user_id, "tenant_id": user.tenant_id, "roles": sorted(user.roles)}, get_settings().jwt_secret, get_settings().jwt_expire_minutes * 60), "token_type": "bearer"}


@router.post("/login")
def login(request: LoginRequest, db: Session | None = Depends(get_runtime_db)) -> dict[str, str]:
    settings = get_settings()
    allowed = DatabaseRateLimiter(db, settings.login_max_attempts, settings.login_window_seconds).allow(f"login:{request.username}") if db is not None else state.limiter.allow(f"login:{request.username}", settings.login_max_attempts, settings.login_window_seconds)
    if not allowed:
        failed_user = load_user(db, request.username) if db is not None else state.users.get(request.username)
        if failed_user is not None:
            if db is not None:
                append_audit(db, failed_user, "login_failed", {"reason": "lockout"})
            else:
                state.audit(failed_user, "login_failed", {"reason": "lockout"})
        raise HTTPException(status_code=429, detail="login temporarily locked")
    user = authenticate_user(db, request.username, request.password) if db is not None else authenticate(request.username, request.password)
    if user is None:
        if db is not None:
            failed_user = load_user(db, request.username)
            if failed_user is not None:
                append_audit(db, failed_user, "login_failed", {})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    if db is not None:
        append_audit(db, user, "login", {})
    else:
        state.audit(user, "login", {})
    return issue_token(user)


@router.post("/refresh")
def refresh(user=Depends(current_user)) -> dict[str, str]:
    return issue_token(user)
