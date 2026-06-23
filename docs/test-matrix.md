# Test Matrix

This matrix maps the P5 acceptance areas to the tests and commands currently available in this repository. CI intentionally stays lightweight: it does not call real model APIs and does not connect to real RDS.

## Backend Coverage

| Area | What is checked | Current coverage |
| --- | --- | --- |
| Auth | register, login, current user, logout, invalid credentials, protected route behavior | `backend/tests/test_auth.py` |
| Workspace | local workspace isolation, auth-required workspace derivation, cross-workspace denial | `backend/tests/test_workspace.py` |
| File parsing | TXT / MD / DOCX / PDF parsing behavior and unsupported file handling | `backend/tests/test_file_parser.py` |
| Path safety | traversal rejection and safe output path resolution | `backend/tests/test_path_safety.py` |
| Chapter split | Chinese and English chapter detection, fallback chunking | `backend/tests/test_chapter_splitter.py` |
| Prompt rendering | prompt template rendering and missing variable behavior | `backend/tests/test_prompt_renderer.py` |
| Analysis modes | selected analysis modes and dry-run task behavior | `backend/tests/test_modes.py` |
| Knowledge base | document chunk import and lightweight search | `backend/tests/test_knowledge_base.py` |
| Knowledge cards | package import, markdown import, canonical merge/unmerge, disabled/deleted filtering, RAG metadata | `backend/tests/test_knowledge_cards.py` |
| Phase 3 export | Markdown, knowledge package, Obsidian and graph export shape | `backend/tests/test_phase3_exporter.py` |
| RAG | query expansion, canonical-only retrieval, diversity filtering, used knowledge alignment | `backend/tests/test_knowledge_cards.py`, `backend/tests/test_writing_generation.py` |
| Writing agent | dry-run generation, outline/draft/revision prompt paths, provider error handling boundaries | `backend/tests/test_writing_generation.py`, `backend/tests/test_writing_kernel.py`, `backend/tests/test_llm_provider.py` |
| Long text | target-char parsing, segmented generation metadata, supplement cap, char statistics | `backend/tests/test_writing_generation.py` |
| Route contract | frontend writing/auth/knowledge route registration and legacy route status | `backend/tests/test_p1_route_contract.py` |

## Frontend Checks

| Area | Command | Purpose |
| --- | --- | --- |
| Type safety | `npm exec tsc -- --noEmit -p tsconfig.json` | Ensures API client and UI code compile against TypeScript types. |
| Production build | `npm run build` | Ensures the Vite production bundle can be generated for Docker/ECS/Render. |

## CI Gates

GitHub Actions currently checks:

- patch whitespace with `git diff --check`;
- backend `python -m pytest`;
- frontend `npm ci`;
- frontend TypeScript no-emit check;
- frontend production build;
- a lightweight secret smoke test for accidentally tracked `.env` files and common credential patterns.

## Manual Release Checks

These items are intentionally not automated in CI because they depend on the deployment target:

- Docker Compose smoke test: app starts, `/health` returns 200, frontend opens.
- ECS smoke test: Nginx proxy reaches the container bound to `127.0.0.1:8000`.
- RDS smoke test: ECS connects to the RDS internal hostname from the same VPC/security group.
- Full demo workspace: register/login, import sample package, merge cards, edit Canonical Markdown, run RAG preview, confirm Memory, start a long draft job, and continue from Memory.

## Known Test Gaps

- No browser automation suite is currently included.
- No real model API call is run in CI; provider behavior is covered through dry-run and mocked/error-path tests.
- No real MySQL/RDS service is required for CI; ECS/RDS connectivity remains a deployment checklist item.
