from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import current_user
from app.api.state import User, state

router = APIRouter(prefix="/v1/audit", tags=["audit"])


@router.get("/logs")
def logs(user: User = Depends(current_user)) -> list[object]:
    if "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="admin role required")
    return [record for record in state.audits if record.tenant_id == user.tenant_id]


@router.get("/verify")
def verify(user: User = Depends(current_user)) -> dict[str, object]:
    from app.audit.hashchain import verify_chain
    if "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="admin role required")
    records = [record for record in state.audits if record.tenant_id == user.tenant_id]
    valid, broken_id = verify_chain(records)
    return {"valid": valid, "first_broken_id": broken_id}
