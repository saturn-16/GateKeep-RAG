from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.api.runtime import get_runtime_db
from app.api.state import User, state
from app.audit.service import write_audit
from app.core.security import hash_password
from app.db.models import User as DbUser

router = APIRouter(prefix="/v1/admin", tags=["admin"])
KNOWN_ROLES = {"admin", "hr", "finance", "engineering", "legal", "employee", "viewer", "auditor"}


class UserCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    roles: set[str] = set()
    clearance: str = "internal"


class RoleChange(BaseModel):
    role: str = Field(min_length=1, max_length=100)


def require_admin(user: User) -> None:
    if "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="tenant admin required")


def validate_role(role: str) -> None:
    if role not in KNOWN_ROLES:
        raise HTTPException(status_code=400, detail="unknown role")


@router.post("/users")
def create_user(request: UserCreate, user: User = Depends(current_user), db: Session | None = Depends(get_runtime_db)) -> dict[str, object]:
    require_admin(user)
    if not request.roles <= KNOWN_ROLES:
        raise HTTPException(status_code=400, detail="unknown role")
    if db is not None:
        if db.get(DbUser, request.user_id) is not None:
            raise HTTPException(status_code=409, detail="user already exists")
        created = DbUser(id=request.user_id, tenant_id=user.tenant_id, password_hash=hash_password(request.password), clearance=request.clearance, active=True, roles=sorted(request.roles))
        db.add(created)
        audit = write_audit(state, user, "user_create", {"user_id": request.user_id}, db)
        db.commit()
    else:
        if request.user_id in state.users:
            raise HTTPException(status_code=409, detail="user already exists")
        state.users[request.user_id] = User(request.user_id, user.tenant_id, hash_password(request.password), frozenset(request.roles), request.clearance)
        audit = write_audit(state, user, "user_create", {"user_id": request.user_id})
    return {"user_id": request.user_id, "tenant_id": user.tenant_id, "audit_id": audit.id}


@router.post("/users/{user_id}/roles")
def assign_role(user_id: str, request: RoleChange, user: User = Depends(current_user), db: Session | None = Depends(get_runtime_db)) -> dict[str, str]:
    require_admin(user)
    validate_role(request.role)
    if db is not None:
        target = db.scalar(select(DbUser).where(DbUser.id == user_id, DbUser.tenant_id == user.tenant_id))
        if target is None:
            raise HTTPException(status_code=404, detail="user not found")
        target.roles = sorted(set(target.roles or []) | {request.role})
        audit = write_audit(state, user, "role_assign", {"user_id": user_id, "role": request.role}, db)
        db.commit()
    else:
        target = state.users.get(user_id)
        if target is None or target.tenant_id != user.tenant_id:
            raise HTTPException(status_code=404, detail="user not found")
        target.roles = frozenset(set(target.roles) | {request.role})
        audit = write_audit(state, user, "role_assign", {"user_id": user_id, "role": request.role})
    return {"user_id": user_id, "audit_id": audit.id}


@router.delete("/users/{user_id}/roles/{role}")
def revoke_role(user_id: str, role: str, user: User = Depends(current_user), db: Session | None = Depends(get_runtime_db)) -> dict[str, str]:
    require_admin(user)
    validate_role(role)
    if db is not None:
        target = db.scalar(select(DbUser).where(DbUser.id == user_id, DbUser.tenant_id == user.tenant_id))
        if target is None:
            raise HTTPException(status_code=404, detail="user not found")
        target.roles = sorted(set(target.roles or []) - {role})
        audit = write_audit(state, user, "role_revoke", {"user_id": user_id, "role": role}, db)
        db.commit()
    else:
        target = state.users.get(user_id)
        if target is None or target.tenant_id != user.tenant_id:
            raise HTTPException(status_code=404, detail="user not found")
        target.roles = frozenset(set(target.roles) - {role})
        audit = write_audit(state, user, "role_revoke", {"user_id": user_id, "role": role})
    return {"user_id": user_id, "audit_id": audit.id}
