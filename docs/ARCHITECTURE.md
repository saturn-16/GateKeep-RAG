# Architecture

```mermaid
flowchart LR
  R[Request] --> A[JWT auth]
  A --> P[Verified Principal]
  P --> F[Mandatory tenant + ACL pre-filter]
  F --> V[Post-retrieval verifier]
  V --> C[Guarded context]
  C --> L[LLM provider]
  L --> O[Output/citation guard]
  O --> U[Response]
  P -.-> H[Hash-chain audit]
  F -.-> H
  O -.-> H
```

Every chunk carries tenant, roles/users, sensitivity, source, and content hash metadata. The pure `can_access` function and scoped retriever provide the application boundary; a Qdrant adapter can serialize the same filter for pre-filtering.
