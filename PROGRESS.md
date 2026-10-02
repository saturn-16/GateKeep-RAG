# GateKeep RAG Progress

- [x] Phase 0: Scaffold
- [ ] Phase 1: Data model & auth (schema/migration added; DB-backed auth wiring pending)
- [x] Phase 2: Permissions core (unit tests and live tenant isolation pass)
- [x] Phase 3: Vector layer (real Qdrant pre-filter and isolation test pass)
- [ ] Phase 4: Ingestion (multipart parser/background path added; DB status wiring pending)
- [ ] Phase 5: Query pipeline
- [x] Phase 6: Audit system (Postgres trigger and live immutability test pass; DB logger wiring pending)
- [ ] Phase 7: Security hardening (DB rate limiter added; API dependency wiring pending)
- [ ] Phase 8: Eval harness + seed data
- [ ] Phase 9: Demo UI
- [ ] Phase 10: Docs & polish

## Current status
Real infrastructure adapters are being validated. No phase after the scaffold is marked complete until live Qdrant/PostgreSQL tests and API wiring pass.
