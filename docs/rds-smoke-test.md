# RDS / MySQL Smoke Test

This project currently uses a lightweight startup schema upgrade instead of Alembic. The upgrade path is idempotent: startup checks for missing columns and indexes before running `ALTER TABLE` or `CREATE INDEX`.

## Configuration

Use an explicit MySQL URL. Do not leave `APP_DATABASE_URL` unset in ECS/RDS deployments.

```bash
APP_DATABASE_URL=mysql+pymysql://<user>:<url_encoded_password>@<rds-internal-host>:3306/<database>?charset=utf8mb4
```

The app does not silently fall back to SQLite when MySQL initialization fails. A failed RDS connection should stop startup with a clear database initialization error.

## Startup Check

1. Start the backend with the RDS URL configured.
2. Confirm startup completes without duplicate column or duplicate index errors.
3. Restart the backend once more to verify the schema upgrade is repeatable.
4. Confirm `knowledge_cards` has these retrieval columns:
   `source_refs_json`, `retrieval_level`, `context_role`, `normalized_title_hash`, `canonical_group_id`.

## Index Check

Confirm these indexes exist on `knowledge_cards`:

```sql
SHOW INDEX FROM knowledge_cards WHERE Key_name IN (
  'idx_card_kb_library_status',
  'idx_card_scope_position',
  'idx_card_visibility_window',
  'idx_card_type_priority',
  'idx_card_content_hash',
  'idx_card_title_group'
);
```

None of these indexes should include `TEXT` columns.

## Scoped RAG Check

1. Import or create approved canonical cards for one work.
2. Add raw cards and future chapter cards.
3. Call `/api/writing/works/{work_id}/rag/search` with `current_volume_index=1` and `current_chapter_index=1`.
4. Verify default results exclude:
   `raw_extracted`, non-canonical, non-retrievable, merged/deleted/deprecated/superseded/disabled, future volume, future chapter, and other work IDs.
5. Inspect `retrieval_debug` for:
   `candidate_count_after_db_filter`, `raw_cards_excluded_count`, `future_cards_excluded_count`, `source_cap_excluded_count`, and `selected_scope_distribution`.

For production-sized RDS data, the DB should reduce candidates before Python strict filtering. Python filtering is still used for reveal windows, validity windows, duplicate caps, card-type quotas, and source caps.
