from dataclasses import dataclass
from typing import Any

from app.core.principal import CLEARANCE_LEVELS, Principal


@dataclass(frozen=True, slots=True)
class ChunkACL:
    tenant_id: str
    chunk_id: str
    allowed_roles: frozenset[str] = frozenset()
    allowed_users: frozenset[str] = frozenset()
    sensitivity: str = "restricted"
    department: str | None = None


def can_access(principal: Principal, chunk_acl: ChunkACL) -> bool:
    """Return whether a principal may read a chunk, using default-deny ACL rules."""
    if principal.tenant_id != chunk_acl.tenant_id:
        return False
    is_admin = "admin" in principal.roles
    has_acl_match = bool(principal.roles & chunk_acl.allowed_roles)
    has_user_grant = principal.user_id in chunk_acl.allowed_users
    is_public = chunk_acl.sensitivity == "public"
    if not is_admin and not (has_acl_match or has_user_grant or is_public):
        return False
    chunk_level = CLEARANCE_LEVELS.get(chunk_acl.sensitivity, -1)
    return is_admin or chunk_level <= principal.clearance_level


def build_filter(principal: Principal) -> dict[str, Any]:
    """Build the mandatory tenant and ACL pre-filter for a vector query."""
    if not principal.tenant_id:
        raise ValueError("tenant context is required")
    return {
        "must": [
            {"key": "tenant_id", "match": {"value": principal.tenant_id}},
            {"key": "sensitivity_level", "range": {"lte": principal.clearance_level}},
        ],
        "should": [
            {"key": "allowed_roles", "match": {"any": sorted(principal.roles)}},
            {"key": "allowed_users", "match": {"value": principal.user_id}},
            {"key": "sensitivity", "match": {"value": "public"}},
        ],
        "minimum_should_match": 1,
    }


def matches_filter(principal: Principal, chunk_acl: ChunkACL) -> bool:
    """Evaluate the logical equivalent of the serialized vector pre-filter."""
    return can_access(principal, chunk_acl)
