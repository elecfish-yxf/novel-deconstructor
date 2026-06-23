# P1 Route Contract Audit

This table records the frontend-to-backend contract for the P1 critical paths. All listed routes are currently registered in FastAPI and covered by `backend/tests/test_p1_route_contract.py`.

| Frontend function | Frontend request path | Backend route | Method | Request schema | Response schema | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `api.register` | `/api/auth/register` | `/api/auth/register` | POST | `AuthRegisterRequest` | `AuthResponse` | exists |
| `api.login` | `/api/auth/login` | `/api/auth/login` | POST | `AuthLoginRequest` | `AuthResponse` | exists |
| `api.me` | `/api/auth/me` | `/api/auth/me` | GET | Bearer token | `AuthMeResponse` | exists |
| `api.logout` | `/api/auth/logout` | `/api/auth/logout` | POST | Bearer token | `{ ok: true }` | exists |
| `api.importKnowledgePackage` | `/api/writing/works/{workId}/knowledge/import-package` | `/api/writing/works/{work_id}/knowledge/import-package` | POST | `KnowledgePackageImportRequest` | `KnowledgePackageImportResponse` | exists |
| `api.importKnowledgeMarkdown` | `/api/writing/works/{workId}/knowledge/import-markdown` | `/api/writing/works/{work_id}/knowledge/import-markdown` | POST | `KnowledgeMarkdownImportRequest` | `KnowledgeMarkdownImportResponse` | exists |
| `api.importKnowledgeMarkdownFile` | `/api/writing/works/{workId}/knowledge/import-markdown-file` | `/api/writing/works/{work_id}/knowledge/import-markdown-file` | POST | multipart file | `KnowledgeMarkdownImportResponse` | exists |
| `api.listKnowledgeCards` | `/api/writing/works/{workId}/knowledge/cards` | `/api/writing/works/{work_id}/knowledge/cards` | GET | query filters | `list[KnowledgeCardRead]` | exists |
| `api.updateKnowledgeCard` | `/api/writing/works/{workId}/knowledge/cards/{cardId}` | `/api/writing/works/{work_id}/knowledge/cards/{card_id}` | PATCH | `KnowledgeCardUpdate` | `KnowledgeCardRead` | exists |
| `api.deleteKnowledgeCard` | `/api/writing/works/{workId}/knowledge/cards/{cardId}` | `/api/writing/works/{work_id}/knowledge/cards/{card_id}` | DELETE | path params | `KnowledgeCardRead` | exists |
| `api.listKnowledgeMarkdownDocs` | `/api/writing/works/{workId}/knowledge/docs` | `/api/writing/works/{work_id}/knowledge/docs` | GET | path params | `list[KnowledgeMarkdownDocRead]` | exists |
| `api.syncKnowledgeMarkdownDoc` | `/api/writing/works/{workId}/knowledge/docs/{docId}/sync` | `/api/writing/works/{work_id}/knowledge/docs/{doc_id}/sync` | POST | path params | `KnowledgeMarkdownSyncResponse` | exists |
| `api.searchWorkRAG` | `/api/writing/works/{workId}/rag/search` | `/api/writing/works/{work_id}/rag/search` | POST | `RAGSearchRequest` | `RAGSearchResponse` | exists |
| `api.generateWorkOutline` | `/api/writing/works/{workId}/agent/outline` | `/api/writing/works/{work_id}/agent/outline` | POST | `WritingOutlineRequest` | `WritingGenerateResponse` | exists |
| `api.generateWorkDraft` | `/api/writing/works/{workId}/agent/draft` | `/api/writing/works/{work_id}/agent/draft` | POST | `WritingDraftRequest` | `WritingGenerateResponse` | exists |
| `api.createWorkDraftJob` | `/api/writing/works/{workId}/agent/draft-jobs` | `/api/writing/works/{work_id}/agent/draft-jobs` | POST | `WritingDraftRequest` | `WritingDraftJobRead` | exists |
| `api.getWorkDraftJob` | `/api/writing/works/{workId}/agent/draft-jobs/{jobId}` | `/api/writing/works/{work_id}/agent/draft-jobs/{job_id}` | GET | path params | `WritingDraftJobRead` | exists |
| `api.cancelWorkDraftJob` | `/api/writing/works/{workId}/agent/draft-jobs/{jobId}/cancel` | `/api/writing/works/{work_id}/agent/draft-jobs/{job_id}/cancel` | POST | path params | `WritingDraftJobRead` | exists |
| `api.generateWorkRevision` | `/api/writing/works/{workId}/agent/revision` | `/api/writing/works/{work_id}/agent/revision` | POST | `WritingRevisionRequest` | `WritingGenerateResponse` | exists |
| `api.confirmOutlineMemory` | `/api/writing/works/{workId}/memory/confirm-outline` | `/api/writing/works/{work_id}/memory/confirm-outline` | POST | `WritingMemoryConfirmRequest` | `WritingMemoryRead` | exists |
| `api.confirmDraftMemory` | `/api/writing/works/{workId}/memory/confirm-draft` | `/api/writing/works/{work_id}/memory/confirm-draft` | POST | `WritingMemoryConfirmRequest` | `WritingMemoryRead` | exists |

Legacy compatibility routes remain available but are deprecated in the OpenAPI schema:

| Legacy path | Replacement | Status |
| --- | --- | --- |
| `/api/writing/outline` | `/api/writing/works/{work_id}/agent/outline` | deprecated |
| `/api/writing/draft` | `/api/writing/works/{work_id}/agent/draft` | deprecated |
| `/api/writing/generate` | `/api/writing/works/{work_id}/agent/outline` | deprecated |

Workspace behavior:

- Local demo mode can use legacy workspace headers or query params when `APP_REQUIRE_AUTH=false`.
- Cloud deployment should set `APP_REQUIRE_AUTH=true`.
- When auth is required, protected workspace APIs return `401` without a valid Bearer token.
- After login, the backend derives the workspace from the Bearer token; `work_id` lookups are always filtered by current workspace.
