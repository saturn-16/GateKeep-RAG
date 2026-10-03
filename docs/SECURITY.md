# Security Model

Core invariant: a principal can only retrieve chunks from the verified tenant and permitted clearance/ACL set. The LLM is downstream of this decision and cannot widen it.

## Defense-in-depth checklist

- [x] Tenant filter is derived from verified JWT identity.
- [x] Role, user grant, sensitivity, and default-deny ACL decision is centralized.
- [x] Scoped retriever rejects missing tenant context.
- [x] Prompt builder rejects cross-tenant context.
- [x] Output guard removes unverified citations.
- [x] Audit records use a per-tenant SHA-256 hash chain.
- [x] Passwords use scrypt; access tokens use HMAC-SHA256.
- [x] Request models ignore unknown tenant/role query fields.
- [x] Database role separation: application operates with non-owner role (`gatekeep_app`).
- [ ] Production rate limiting remains deployment work.

## Database Role Separation & Audit Tamper Detection

1. **Least-Privilege Role Separation**: The runtime application connects using a dedicated non-owner role (`gatekeep_app`). This role holds `SELECT` and `INSERT` permissions on the `audit_logs` table, but `UPDATE`, `DELETE`, and `TRUNCATE` are explicitly revoked. Because `gatekeep_app` does not own the table, PostgreSQL forbids it from executing `ALTER TABLE audit_logs DISABLE TRIGGER ALL` or dropping triggers.
2. **Superuser / DB Owner Bypass Boundary**: In PostgreSQL, a database superuser or the table owner has administrative privileges that can bypass triggers (e.g., via trigger disabling, replica role overrides, or raw storage edits).
3. **Cryptographic Tamper-Evident Hash Chain**: To defend against rogue administrators, superuser compromises, or out-of-band database mutations, GateKeep RAG enforces a per-tenant append-only SHA-256 hash chain (`row_hash = SHA256(prev_hash || tenant_id || user_id || action || details || timestamp)`). Concurrency is synchronized using PostgreSQL transaction advisory locks (`pg_advisory_xact_lock(hashtext(tenant_id))`). Any out-of-band row alteration, deletion, reordering, or backdating breaks the cryptographic chain and is detected during verification via `GET /v1/audit/verify`.

Threats considered: cross-tenant leakage, privilege escalation, stale ACLs, filter bypass, prompt injection, audit tampering, embedding inversion, and side channels. Prompt injection is treated as untrusted document text; access is enforced before generation.
