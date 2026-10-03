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
- [ ] Production rate limiting and database privilege revocation remain deployment work.

Threats considered: cross-tenant leakage, privilege escalation, stale ACLs, filter bypass, prompt injection, audit tampering, embedding inversion, and side channels. Prompt injection is treated as untrusted document text; access is enforced before generation.
