# Prompt Coverage Audit

This audit maps `Novel_Deconstructor_90_prompt_full_split.md` to the repository state after the optimization pass.

## Coverage Summary

| Prompt section | Status | Evidence |
| --- | --- | --- |
| Global positioning and loop | Covered | README describes the full deconstruction -> cards -> RAG -> Agent -> Memory loop and the personal-project boundary. |
| P1 deployment and route alignment | Covered | `deploy/ecs.md`, `README.md`, `docs/p1-route-audit.md`, `backend/tests/test_p1_route_contract.py`. |
| P1 auth/workspace docs | Covered | README and route audit document local legacy workspace, cloud auth requirement and Bearer-token workspace derivation. |
| P2 knowledge model and package import | Covered | KnowledgeCard fields, package import, Markdown generation and tests in `backend/tests/test_knowledge_cards.py`. |
| P2 canonical merge and Markdown sync | Covered | Merge preview/apply/unmerge, canonical-only retrieval and Markdown sync are implemented and tested. |
| P3 RAG boundary and debug output | Covered | `services/rag_retrieval.py`, stage-aware retrieval, `used_knowledge` and `retrieval_debug`. |
| P3 Agent outline/draft/revision and Memory | Covered | Updated Agent routes, dry-run prompt preview, memory confirmation routes and route contract test. |
| P4 long text planning and supplement | Covered | Long draft section metadata, char stats, supplement cap and warnings are implemented and tested. |
| P4 async draft job UI | Covered with limitation | Draft job create/get/cancel and frontend polling exist; job state is in-memory, not durable after backend restart. |
| P5 test matrix and CI | Covered | `docs/test-matrix.md` and CI backend/frontend/security jobs. |
| P5 README/demo/comparison | Covered | `examples/sample_canonical_cards.json`, `examples/comparison_without_vs_with_rag.md` and expanded README Demo Flow. |
| P5 security/release/final report | Covered | `docs/security-release-checklist.md`, `docs/code-quality-boundaries.md`, `docs/final-delivery-report.md`. |

## Intentional Deviations

- ECS + Docker + Nginx + Aliyun RDS MySQL is now the recommended formal deployment path. Render + MySQL/RDS language from the original prompt is kept only as optional/rollback context because the deployment target has changed to ECS.
- No vector database, GraphRAG, LangChain or Kubernetes was introduced. The prompt explicitly allows a lightweight SQLite / keyword / tag / card_type implementation.
- No durable long-job queue was added. The current in-memory job model fits local/ECS single-process deployment and is documented as a limitation.
- No full browser automation suite was introduced. Backend, route-contract and frontend build checks cover the main regressions; Docker/ECS/RDS/browser smoke tests remain release-time manual checks.
- No large service extraction was performed after tests were green. `api/writing.py` and `knowledge_cards.py` are documented as future refactor targets rather than churned during release stabilization.

## Current Verification Snapshot

Latest local verification recorded in `docs/final-delivery-report.md`:

- Backend pytest: 62 passed.
- Frontend TypeScript no-emit check: passed.
- Frontend production build: passed.
- Whitespace check: passed with CRLF warnings only.
- Tracked `.env` check: passed.
- Tracked common-secret pattern scan: passed.

## Remaining Manual Checks Before Public Release

- Run Docker Compose or ECS container smoke on the target machine.
- Confirm `/health` returns 200 through Nginx.
- Confirm ECS can connect to RDS through the internal hostname.
- Run the README demo flow in a fresh workspace through the browser.
- Keep Render for 1-3 days only as rollback backup, then pause or delete it after ECS is stable.
