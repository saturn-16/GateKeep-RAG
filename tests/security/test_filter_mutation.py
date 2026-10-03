import pytest
from typing import Any

from app.core import permissions
from app.core.permissions import ChunkACL
from app.core.principal import CLEARANCE_LEVELS, Principal
from app.rag.vectorstore.tenant_scoped_retriever import VectorChunk


def _apply_filter(filter_spec: dict[str, object], chunks: list[ChunkACL]) -> list[ChunkACL]:
    required_tenant = next((item["match"]["value"] for item in filter_spec["must"] if item["key"] == "tenant_id"), None)
    if required_tenant is None:
        return chunks
    return [chunk for chunk in chunks if chunk.tenant_id == required_tenant]


def _filter_chunks(filter_spec: dict[str, Any], chunks: list[VectorChunk], require_status_ready: bool = True) -> list[VectorChunk]:
    must_items = {item["key"]: item for item in filter_spec.get("must", [])}
    tenant_val = must_items.get("tenant_id", {}).get("match", {}).get("value")
    max_clearance = must_items.get("sensitivity_level", {}).get("range", {}).get("lte", 99)

    should_items = filter_spec.get("should", [])
    allowed_roles_matcher = next((item.get("match", {}).get("any", []) for item in should_items if item.get("key") == "allowed_roles"), None)

    matched = []
    for chunk in chunks:
        if tenant_val is not None and chunk.acl.tenant_id != tenant_val:
            continue
        if require_status_ready and chunk.document_status != "ready":
            continue
        chunk_level = CLEARANCE_LEVELS.get(chunk.acl.sensitivity, -1)
        if chunk_level > max_clearance:
            continue
        if should_items:
            has_role_match = bool(set(allowed_roles_matcher or []) & chunk.acl.allowed_roles) if allowed_roles_matcher is not None else True
            has_public = chunk.acl.sensitivity == "public"
            if not (has_role_match or has_public):
                continue
        matched.append(chunk)
    return matched


def run_counterfactual_assertion(principal: Principal, filter_spec: dict[str, Any], world1: list[VectorChunk], world2: list[VectorChunk], require_status: bool = True) -> None:
    res1 = [c.acl.chunk_id for c in _filter_chunks(filter_spec, world1, require_status_ready=require_status)]
    res2 = [c.acl.chunk_id for c in _filter_chunks(filter_spec, world2, require_status_ready=require_status)]
    assert res1 == res2, f"Counterfactual divergence: World 1 {res1} != World 2 {res2}"


def test_tenant_isolation_test_fails_when_tenant_condition_is_mutated(monkeypatch: pytest.MonkeyPatch) -> None:
    original = permissions.build_filter

    def mutated(principal: Principal) -> dict[str, object]:
        result = original(principal)
        result["must"] = [item for item in result["must"] if item["key"] != "tenant_id"]
        return result

    monkeypatch.setattr(permissions, "build_filter", mutated)
    principal = Principal("dave", "acme", frozenset({"employee"}), "internal")
    chunks = [ChunkACL("acme", "a", frozenset({"employee"}), sensitivity="internal"), ChunkACL("globex", "g", frozenset({"employee"}), sensitivity="internal")]
    with pytest.raises(AssertionError):
        assert [chunk.tenant_id for chunk in _apply_filter(permissions.build_filter(principal), chunks)] == ["acme"]


def test_counterfactual_fails_when_role_condition_is_removed_from_build_filter() -> None:
    principal = Principal("dave", "acme", frozenset({"employee"}), "internal")
    permitted = VectorChunk(ChunkACL("acme", "chunk-permitted", frozenset({"employee"}), sensitivity="internal"), "Handbook", 0.8, "doc-handbook", "ready")
    restricted = VectorChunk(ChunkACL("acme", "chunk-restricted", frozenset({"hr"}), sensitivity="internal"), "Salary", 0.9, "doc-salary", "ready")

    world1 = [permitted]
    world2 = [permitted, restricted]

    # Baseline valid filter: Dave gets only permitted chunk in both worlds -> invariance holds
    valid_filter = permissions.build_filter(principal)
    run_counterfactual_assertion(principal, valid_filter, world1, world2)

    # Mutated filter: tenant condition kept, but role condition removed
    mutated_filter = permissions.build_filter(principal)
    mutated_filter["should"] = []  # Drop role requirement, matching everything in tenant

    with pytest.raises(AssertionError, match="Counterfactual divergence"):
        run_counterfactual_assertion(principal, mutated_filter, world1, world2)


def test_counterfactual_fails_when_status_filter_is_removed() -> None:
    principal = Principal("dave", "acme", frozenset({"employee"}), "internal")
    permitted = VectorChunk(ChunkACL("acme", "chunk-permitted", frozenset({"employee"}), sensitivity="internal"), "Handbook", 0.8, "doc-handbook", "ready")
    unready = VectorChunk(ChunkACL("acme", "chunk-unready", frozenset({"employee"}), sensitivity="internal"), "Draft Policy", 0.85, "doc-unready", "processing")

    world1 = [permitted]
    world2 = [permitted, unready]

    valid_filter = permissions.build_filter(principal)
    # With status filter enforced (require_status=True): invariance holds
    run_counterfactual_assertion(principal, valid_filter, world1, world2, require_status=True)

    # When status filter is removed/disabled (require_status=False): unready doc leaks into World 2
    with pytest.raises(AssertionError, match="Counterfactual divergence"):
        run_counterfactual_assertion(principal, valid_filter, world1, world2, require_status=False)