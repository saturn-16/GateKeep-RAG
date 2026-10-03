# GateKeep RAG Progress

- [x] Phase 0: Scaffold
- [x] Phase 1: Data model & auth (PostgreSQL login, refresh, me, and request-time role reload verified)
- [x] Phase 2: Permissions core (unit tests and live tenant isolation pass)
- [x] Phase 3: Vector layer (real Qdrant pre-filter and isolation test pass)
- [ ] Phase 4: Ingestion (multipart parser/background path added; DB status wiring pending)
- [x] Phase 5: Query pipeline (pre-filter, DB post-verification, guarded prompt/citations, MockLLM/Ollama)
- [x] Phase 6: Audit system (DB logger, tenant-scoped endpoints, exports, verification, and tamper test pass)
- [x] Phase 7: Security hardening (login/query rate limits, lockout audits, mutation and concurrency tests)
- [x] Phase 8: Eval harness + seed data (live seed, attack demo, recall/MRR, leak rate 0.000)
- [ ] Phase 9: Demo UI
- [ ] Phase 10: Docs & polish

## Current status
Real infrastructure adapters, live security tests, and CI service configuration are in place. Remaining unchecked items are explicitly listed in docs/REQUIREMENTS_MATRIX.md.
