from dataclasses import replace

from app.audit.hashchain import make_record, verify_chain
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.rag.generation.output_guard import guard_output


def test_password_and_token_round_trip() -> None:
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("scrypt$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)

    # Verify backward-compatibility fallback with legacy N=2^14 fixture
    import hashlib, os
    from app.core.security import _b64
    legacy_salt = os.urandom(16)
    legacy_digest = hashlib.scrypt(b"legacy_pass", salt=legacy_salt, n=2**14, r=8, p=1)
    legacy_encoded = f"scrypt${_b64(legacy_salt)}${_b64(legacy_digest)}"
    assert verify_password("legacy_pass", legacy_encoded)
    assert not verify_password("wrong", legacy_encoded)

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
