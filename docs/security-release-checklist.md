# Security And Release Checklist

Use this checklist before promoting ECS as the active deployment or before keeping Render as a rollback backup. It is deliberately lightweight and does not replace a dedicated secret scanner.

## Local Repository

Run these checks from the repository root:

```bash
git status --short
git diff --check
git ls-files | grep -E '(^|/)\.env($|\.)' | grep -vE '(^|/)\.env\.example$'
git grep -nE '(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|AKTP[0-9A-Za-z_-]{20,}|mysql\+pymysql://[^<[:space:]]+:[^<[:space:]]+@)'
```

Expected result:

- `.env` and `.env.*` are not tracked, except `.env.example`.
- No real model key, cloud access key, database password, or production DSN appears in committed files.
- `render.yaml` contains only placeholders or non-secret defaults.
- examples contain only copyright-safe demo text.

If a real secret was ever committed, rotate it. Removing it from the working tree is not enough.

## Runtime Privacy

Confirm before public deployment:

- `APP_REQUIRE_AUTH=true` is enabled on ECS and any temporary Render service.
- Logs do not print `Authorization`, raw `api_key`, model keys, database passwords, or full user prompts when they may contain private text.
- User-entered model keys are request-scoped and are not stored in the database.
- Uploaded texts and generated outputs are stored on the server; users should understand that model calls send relevant prompt and knowledge snippets to the selected provider.

## ECS Checklist

- Container binds only to the local interface, for example `127.0.0.1:8000:8000`.
- Nginx is the public entry point and handles HTTPS.
- `APP_DATABASE_URL` points to the Aliyun RDS MySQL internal hostname, not the public hostname.
- ECS and RDS are in the same VPC when using the internal hostname.
- RDS security group or whitelist permits the ECS security group/private IP on port `3306`.
- ECS security group opens only required public ports, usually `80` and `443`; SSH should be restricted.
- Runtime directories are mounted or otherwise backed up as needed: storage, uploads, outputs and knowledge.

## Render Rollback Backup

Render remains optional and temporary:

- Keep `render.yaml`; it is only used by Render and does not affect ECS.
- Keep Render for 1-3 days after ECS goes live as a rollback path.
- Confirm the Render service is on the latest commit before treating it as a backup.
- After ECS is stable, pause or delete the Render service to avoid double-running and extra cost.

## Docker Smoke

Before release, run a local or server-side smoke test:

```bash
docker compose up --build
curl http://localhost:8000/health
```

Then open the frontend, register/login when auth is enabled, import the demo knowledge package, run a RAG preview and start a dry-run draft job.
