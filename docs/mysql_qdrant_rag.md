# MySQL, Qdrant, and RAG Deployment Notes

This service still supports local SQLite by default. MySQL/RDS, Qdrant, and real embeddings are optional production integrations. If Qdrant or embeddings are unavailable, writing retrieval falls back to keyword search instead of blocking the app.

## Architecture

- SQL database is the source of truth for knowledge bases, uploaded documents, chunks, cards, and writing memories.
- Qdrant is an index layer used for vector retrieval only. It can be rebuilt from SQL at any time.
- The embedding provider supports `fake` for local tests and `openai-compatible` for production embedding APIs.
- Retrieval modes:
  - `keyword`: SQL/card keyword retrieval only.
  - `vector`: vector retrieval, with keyword fallback when vector dependencies fail.
  - `hybrid`: keyword plus vector, with dedupe, type routing, priority, and diversity caps.

## Environment

Local SQLite defaults:

```env
APP_DATABASE_URL=sqlite:///./storage/novel_deconstructor.db
RETRIEVAL_MODE=keyword
EMBEDDING_PROVIDER=fake
```

Production MySQL/RDS example:

```env
APP_DATABASE_URL=mysql+pymysql://USER:URL_ENCODED_PASSWORD@MYSQL_HOST:3306/novel_deconstructor_prod?charset=utf8mb4
```

Use the RDS internal endpoint when the backend runs on ECS in the same VPC. URL-encode special characters in the password before placing it in `APP_DATABASE_URL`.

Qdrant and embedding example:

```env
RETRIEVAL_MODE=hybrid
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=
QDRANT_COLLECTION=novel_knowledge
QDRANT_VECTOR_SIZE=1536
QDRANT_DISTANCE=Cosine

EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_API_KEY=replace_me
EMBEDDING_BATCH_SIZE=32
EMBEDDING_TIMEOUT_SECONDS=30
```

`EMBEDDING_VECTOR_SIZE` and `QDRANT_VECTOR_SIZE` should match the embedding model dimension. The OpenAI-compatible provider validates response dimensions and fails the vector path early if the provider returns the wrong size.

The backend also validates point vector dimensions before upsert and reports whether the existing Qdrant collection size/distance matches the current config in `/api/rag/health`. If the embedding dimension changes, use a new `QDRANT_COLLECTION` name or recreate the existing collection, then run a force rebuild.

## MySQL/RDS Notes

The current application initializes tables through SQLAlchemy metadata at startup. No Alembic migration flow is required for the current deployment shape. For a fresh RDS database:

1. Create the database with `utf8mb4`.
2. Create a least-privilege user for the app.
3. Set `APP_DATABASE_URL` with `charset=utf8mb4`.
4. Start the backend once so tables are created.
5. Run backend tests or a smoke request against `/api/config/public`.

Recommended RDS settings:

- Character set: `utf8mb4`
- Collation: `utf8mb4_unicode_ci` or the RDS default `utf8mb4` collation
- Network: private VPC security group allowing only the backend/ECS security group
- Credentials: store in environment variables or secret manager, not in source control

## Qdrant Lifecycle

Qdrant is rebuildable. Deleting a knowledge base or knowledge document attempts to delete matching Qdrant payloads, but SQL remains authoritative.

Point IDs are deterministic UUIDv5 values derived from source type and source ID. Business IDs such as `card_id`, `document_id`, `chunk_id`, and `memory_id` remain in payload fields so delete/rebuild operations still work by payload filters while staying compatible with Qdrant point ID requirements.

Health:

```bash
curl http://localhost:8000/api/rag/health
```

Dry-run rebuild for a knowledge base:

```bash
curl -X POST http://localhost:8000/api/rag/rebuild \
  -H "Content-Type: application/json" \
  -H "X-Workspace-Id: anonymous" \
  -d '{"knowledge_base_ids":[1],"dry_run":true}'
```

Force rebuild for a knowledge base:

```bash
curl -X POST http://localhost:8000/api/rag/rebuild \
  -H "Content-Type: application/json" \
  -H "X-Workspace-Id: anonymous" \
  -d '{"knowledge_base_ids":[1],"dry_run":false,"force":true}'
```

Preview retrieval:

```bash
curl -X POST http://localhost:8000/api/rag/preview \
  -H "Content-Type: application/json" \
  -H "X-Workspace-Id: anonymous" \
  -d '{"knowledge_base_ids":[1],"query":"rain oath beacon","phase":"draft","target_volume_index":1,"target_chapter_index":1,"top_k":8}'
```

The frontend resource result tab exposes the same health, dry-run rebuild, force rebuild, and preview/debug actions.

## Retrieval Debug Fields

The preview and writing APIs expose `retrieval_debug` with:

- requested and effective retrieval mode
- scope filters
- vector, keyword, merged, and final candidate counts
- fallback reason when vector retrieval fails
- dropped candidate reasons such as scope, stale payload, duplicate merge, or diversity caps
- score weights and selected top-k metadata

`used_knowledge` is intentionally compact. It includes `source_type`, `reason`, and `concise_content` so prompts can cite useful context without carrying large raw payloads.

## Pre-GraphRAG Payload Fields

Vector payloads include optional graph extension fields for future GraphRAG work:

- `entity_ids`
- `relation_ids`
- `graph_tags`
- `depends_on_card_ids`
- `contradicts_card_ids`
- `supports_card_ids`
- `reveals_card_ids`

These fields are currently stored as payload metadata only. They do not change ranking unless future graph traversal is added.

## Troubleshooting

- `qdrant_available=false`: check `QDRANT_URL`, network/security group, and container health. Retrieval should continue through keyword fallback.
- `dimension mismatch`: set `QDRANT_VECTOR_SIZE` and `EMBEDDING_VECTOR_SIZE` to the embedding model dimension. If the existing collection was created with another size or distance, use a new `QDRANT_COLLECTION` or recreate the collection, then force rebuild.
- `Embedding request failed`: check `EMBEDDING_BASE_URL`, model name, API key, and provider compatibility with `/embeddings`.
- Empty preview: verify the selected workspace and knowledge base IDs, then run rebuild dry-run to confirm planned documents/cards/memories.
- RDS connection failures: verify the RDS endpoint, database name, user, URL-encoded password, VPC routing, and security group ingress from the backend host.
