import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class AuditRecord:
    id: str
    tenant_id: str
    user_id: str
    action: str
    details: dict[str, object]
    timestamp: str
    prev_hash: str
    row_hash: str


def canonical_payload(record: AuditRecord) -> str:
    return json.dumps({"id": record.id, "tenant_id": record.tenant_id, "user_id": record.user_id, "action": record.action, "details": record.details, "timestamp": record.timestamp, "prev_hash": record.prev_hash}, sort_keys=True, separators=(",", ":"))


def make_record(record_id: str, tenant_id: str, user_id: str, action: str, details: dict[str, object], prev_hash: str = "") -> AuditRecord:
    timestamp = datetime.now(timezone.utc).isoformat()
    provisional = AuditRecord(record_id, tenant_id, user_id, action, details, timestamp, prev_hash, "")
    return provisional_with_hash(provisional)


def provisional_with_hash(record: AuditRecord) -> AuditRecord:
    row_hash = hashlib.sha256((record.prev_hash + canonical_payload(record)).encode()).hexdigest()
    return AuditRecord(record.id, record.tenant_id, record.user_id, record.action, record.details, record.timestamp, record.prev_hash, row_hash)


def verify_chain(records: list[AuditRecord]) -> tuple[bool, str | None]:
    previous = ""
    for record in records:
        expected = provisional_with_hash(AuditRecord(record.id, record.tenant_id, record.user_id, record.action, record.details, record.timestamp, previous, ""))
        if record.prev_hash != previous or record.row_hash != expected.row_hash:
            return False, record.id
        previous = record.row_hash
    return True, None
