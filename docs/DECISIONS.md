# Decisions

## Shared Qdrant collection
Use one shared collection with mandatory server-built `tenant_id` payload filtering. This keeps operations simple while preserving a single, testable isolation boundary. Route handlers never receive a raw vector-store client.

## Default local path
The demo defaults to deterministic hashing/in-process retrieval and `MockLLM`, so tests and demos run without API credits. Qdrant, PostgreSQL, local embedding models, and Ollama are integration extensions.

## Identity freshness
The dependency re-checks the active user record on every request. This makes role deactivation effective on the next request instead of trusting long-lived JWT role claims.

## Audit integrity
Audit rows form a per-tenant SHA-256 chain. The application only exposes append and verify operations; production deployment should additionally revoke UPDATE/DELETE privileges for the application database role.

## Integration boundary
The real Qdrant adapter is verified locally with Qdrant's embedded engine. The Docker-backed Qdrant/PostgreSQL integration test is gated by `RUN_REAL_STACK=1` and is not counted as passed when Docker is unavailable.
