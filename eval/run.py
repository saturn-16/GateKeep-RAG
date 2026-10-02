"""Minimal deterministic retrieval/isolation evaluation."""

from app.api.state import state
from app.core.principal import Principal

questions = [("acme", Principal("dave", "acme-corp", frozenset({"employee"}), "internal"), "salary band engineers"), ("hr", Principal("bob", "acme-corp", frozenset({"hr"}), "restricted"), "salary band engineers")]
leaks = 0
for label, principal, question in questions:
    results = state.retriever.search(principal, question)
    ids = [result.acl.tenant_id for result in results]
    leak = any(tenant != principal.tenant_id for tenant in ids)
    leaks += int(leak)
    print(f"{label:8} results={len(results):2} leak={int(leak)}")
print(f"isolation_leak_rate={leaks / len(questions):.1f}")
