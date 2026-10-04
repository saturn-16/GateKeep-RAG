from dataclasses import replace

from app.audit.hashchain import make_record, verify_chain
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.rag.generation.output_guard import guard_output


def test_password_and_token_round_trip() -> None:
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("scrypt$131072$8$1$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)

    # Verify custom stored parameters are strictly parsed and verified without blind fallback
    custom_encoded = hash_password("custom_pass", n=2**14, r=8, p=1)
    assert custom_encoded.startswith("scrypt$16384$8$1$")
    assert verify_password("custom_pass", custom_encoded)
    assert not verify_password("wrong", custom_encoded)

    # Malformed hashes, invalid algorithms, or corrupted parameter fields return False
    assert not verify_password("pass", "argon2id$v=19$...")
    assert not verify_password("pass", "scrypt$invalid$8$1$salt$digest")
    assert not verify_password("pass", "scrypt$16384$8$salt$digest")
    assert not verify_password("pass", "scrypt$0$8$1$salt$digest")

    # Reject out-of-bounds parameters (N > 2^18, r > 16, p > 4)
    assert not verify_password("pass", f"scrypt${2**19}$8$1$salt$digest")
    assert not verify_password("pass", "scrypt$131072$17$1$salt$digest")
    assert not verify_password("pass", "scrypt$131072$8$5$salt$digest")

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
