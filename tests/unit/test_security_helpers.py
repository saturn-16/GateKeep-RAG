from dataclasses import replace

from app.audit.hashchain import make_record, verify_chain
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.rag.generation.output_guard import guard_output


def test_password_and_token_round_trip() -> None:
    encoded = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)
    token = create_access_token({"sub": "alice", "tenant_id": "acme", "roles": ["admin"]}, "test", 60)
    assert decode_access_token(token, "test")["sub"] == "alice"


def test_output_guard_removes_unverified_citations() -> None:
    assert guard_output("Answer [allowed] and [secret]", {"allowed"}) == "Answer [allowed] and"


def test_audit_hash_chain_detects_tampering() -> None:
    first = make_record("1", "acme", "alice", "query", {"question_hash": "x"})
    second = make_record("2", "acme", "alice", "query", {}, first.row_hash)
    assert verify_chain([first, second]) == (True, None)
    tampered = replace(second, details={"changed": True})
    assert verify_chain([first, tampered])[0] is False
