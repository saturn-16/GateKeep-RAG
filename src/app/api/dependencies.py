from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.state import User, state
from app.config import get_settings
from app.core.principal import Principal
from app.core.security import decode_access_token

bearer = HTTPBearer(auto_error=False)


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    try:
        claims = decode_access_token(credentials.credentials, get_settings().jwt_secret)
        user = state.users.get(str(claims.get("sub")))
        if user is None or not user.active or user.tenant_id != claims.get("tenant_id"):
            raise ValueError("inactive or mismatched user")
        return user
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid authentication") from exc


def principal(user: User = Depends(current_user)) -> Principal:
    return Principal(user.user_id, user.tenant_id, user.roles, user.clearance)
