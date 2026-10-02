from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, status

from app.api.state import authenticate, state
from app.config import get_settings
from app.core.security import create_access_token

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
def login(request: LoginRequest) -> dict[str, str]:
    user = authenticate(request.username, request.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    state.audit(user, "login", {})
    token = create_access_token({"sub": user.user_id, "tenant_id": user.tenant_id, "roles": sorted(user.roles)}, get_settings().jwt_secret, get_settings().jwt_expire_minutes * 60)
    return {"access_token": token, "token_type": "bearer"}
