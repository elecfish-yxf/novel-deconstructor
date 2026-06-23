# Code Quality Boundaries

This document records the current service boundaries after the P1-P5 optimization pass. It is intentionally conservative: the current code is test-covered and working, so large mechanical refactors should wait until there is a concrete feature or bug that justifies them.

## Current Boundaries

| Area | Current home | Responsibility |
| --- | --- | --- |
| Writing API coordination | `backend/novel_deconstructor/api/writing.py` | Auth/workspace checks, request validation, response assembly and current Agent orchestration. |
| Knowledge cards and markdown | `backend/novel_deconstructor/services/knowledge_cards.py` | Knowledge package import, Markdown import/sync, canonical merge/unmerge, card search and debug metadata. |
| RAG service entry point | `backend/novel_deconstructor/services/rag_retrieval.py` | Thin retrieval boundary used by Agent calls; ready for future vector/reranker replacement. |
| Model providers | `backend/novel_deconstructor/services/llm_provider.py` | OpenAI-compatible and Doubao-compatible calls, provider errors and response extraction. |
| Deconstruction jobs | `backend/novel_deconstructor/services/pipeline.py` | Background deconstruction task execution and job logs. |
| Auth/workspace | `backend/novel_deconstructor/services/auth.py`, `backend/novel_deconstructor/api/workspace.py` | Password hashing, session token lookup and workspace derivation. |

## Current Risk Notes

- `api/writing.py` is still large because it contains Agent prompt assembly, long-draft planning, background draft jobs and response conversion. It is acceptable for the current release because tests cover the critical route and generation behavior.
- `knowledge_cards.py` is also large because card import, Markdown sync, merge and lightweight retrieval all share the same card model and helper functions.
- `UserAPIKey` exists as an older/dormant model shape, but current request-time model keys are not exposed through a save-key API and are not persisted by Agent generation. Keep this behavior unless a future explicit key-vault feature is designed.
- Long draft jobs are in-memory. They are useful for local/ECS single-process deployment, but they are not a durable queue.

## Refactor Targets When Needed

Only split these when there is a real maintenance benefit and tests stay green:

- Move prompt assembly and Agent stage coordination from `api/writing.py` into `services/writing_agent.py`.
- Move long-text planning, section generation, supplement and final padding into `services/long_generation.py`.
- Move draft job state into a durable database-backed service if process-restart recovery becomes required.
- Move JSON parsing/serialization helpers shared by cards and Agent responses into a small utility module.
- Keep `rag_retrieval.py` as the stable boundary for future vector search or reranking.

## Safety Rules For Future Changes

- Do not log or persist runtime API keys.
- Do not store user prompts in logs unless the user explicitly opts into diagnostic logging.
- Keep deprecated legacy writing routes until the frontend no longer needs them and a compatibility note is added.
- Keep Render compatibility files while ECS is being validated.
- Keep all public Agent behavior available in dry-run mode.
- Add or update tests for every new API route or response field.
