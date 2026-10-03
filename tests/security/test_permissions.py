from app.core.permissions import ChunkACL, build_filter, can_access, matches_filter
from app.core.principal import Principal


def principal(user_id: str, tenant_id: str = "acme", roles: set[str] | None = None, clearance: str = "restricted") -> Principal:
    return Principal(user_id, tenant_id, frozenset(roles or {"employee"}), clearance)


def test_tenant_and_role_are_both_required() -> None:
    acl = ChunkACL("acme", "salary", frozenset({"hr"}), sensitivity="restricted")
    assert can_access(principal("bob", roles={"hr"}), acl)
    assert not can_access(principal("dave"), acl)
    assert not can_access(principal("bob", tenant_id="globex", roles={"hr"}), acl)


def test_public_is_still_tenant_scoped() -> None:
    acl = ChunkACL("acme", "handbook", sensitivity="public")
    assert can_access(principal("dave"), acl)
    assert not can_access(principal("heidi", tenant_id="globex"), acl)


def test_missing_acl_defaults_to_deny_except_admin() -> None:
    acl = ChunkACL("acme", "unclassified")
    assert not can_access(principal("dave"), acl)
    assert can_access(principal("alice", roles={"admin"}), acl)


def test_filter_evaluator_agrees_with_permission_function() -> None:
    principals = [principal("dave"), principal("bob", roles={"hr"}), principal("alice", roles={"admin"})]
    chunks = [
        ChunkACL("acme", "a", frozenset({"employee"}), sensitivity="internal"),
        ChunkACL("acme", "b", frozenset({"hr"}), sensitivity="confidential"),
        ChunkACL("globex", "c", frozenset({"employee"}), sensitivity="public"),
    ]
    for current_principal in principals:
        build_filter(current_principal)
        assert [can_access(current_principal, chunk) for chunk in chunks] == [matches_filter(current_principal, chunk) for chunk in chunks]
