"""Run the core leakage checks and print PASS/FAIL."""

from app.core.permissions import ChunkACL, can_access
from app.core.principal import Principal

checks = {
    "cross tenant denied": not can_access(Principal("dave", "acme-corp", frozenset({"employee"}), "internal"), ChunkACL("globex-inc", "x", frozenset({"employee"}), sensitivity="public")),
    "role denied": not can_access(Principal("dave", "acme-corp", frozenset({"employee"}), "restricted"), ChunkACL("acme-corp", "salary", frozenset({"hr"}), sensitivity="restricted")),
    "admin allowed": can_access(Principal("alice", "acme-corp", frozenset({"admin"}), "restricted"), ChunkACL("acme-corp", "salary", sensitivity="restricted")),
}
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'}: {name}")
if not all(checks.values()):
    raise SystemExit(1)
