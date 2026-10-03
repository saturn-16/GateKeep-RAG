from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.state import User, state
from app.api.runtime import get_runtime_db
from app.config import get_settings
from app.core.principal import Principal
from app.core.security import decode_access_token
from app.db.repository import load_user
from app.audit.service import write_audit
from app.core.rate_limit import DatabaseRateLimiter
from sqlalchemy.orm import Session

bearer = HTTPBearer(auto_error=False)


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session | None = Depends(get_runtime_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    try:
        claims = decode_access_token(credentials.credentials, get_settings().jwt_secret)
        user = load_user(db, str(claims.get("sub"))) if db is not None else state.users.get(str(claims.get("sub")))
        if user is None or not user.active or user.tenant_id != claims.get("tenant_id"):
            raise ValueError("inactive or mismatched user")
        settings = get_settings()
        allowed = DatabaseRateLimiter(db, settings.rate_limit_per_minute, 60).allow(f"query:{user.tenant_id}:{user.user_id}") if db is not None else state.limiter.allow(f"query:{user.tenant_id}:{user.user_id}", settings.rate_limit_per_minute, 60)
        if not allowed:
            write_audit(state, user, "access_denied", {"resource": "query", "reason": "rate_limit"}, db)
            raise HTTPException(status_code=429, detail="query rate limit exceeded")
        return user
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid authentication") from exc


def principal(user: User = Depends(current_user)) -> Principal:
    return Principal(user.user_id, user.tenant_id, user.roles, user.clearance)
