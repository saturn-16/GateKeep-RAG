from dataclasses import dataclass


CLEARANCE_LEVELS = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    clearance: str = "internal"

    @property
    def clearance_level(self) -> int:
        return CLEARANCE_LEVELS.get(self.clearance, -1)
