import pytest

from app.core import permissions
from app.core.permissions import ChunkACL
from app.core.principal import Principal


def _apply_filter(filter_spec: dict[str, object], chunks: list[ChunkACL]) -> list[ChunkACL]:
    required_tenant = next((item["match"]["value"] for item in filter_spec["must"] if item["key"] == "tenant_id"), None)
    if required_tenant is None:
        return chunks
    return [chunk for chunk in chunks if chunk.tenant_id == required_tenant]


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