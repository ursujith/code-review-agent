# Milestone 2 patch — tenant context and PostgreSQL RLS

Copy these files into the matching paths in the existing project, replacing the
existing `app/db/session.py`, `app/api/deps.py`, and `app/api/routes/auth.py`.

## Apply
1. Ensure `.env` points to `localhost:5435` for PostgreSQL.
2. Confirm the five base tables already exist.
3. Run `python -m scripts.enable_dev_rls` while `.env` still uses the bootstrap `review` database user.
4. Run `python -m scripts.create_app_role` while `.env` still uses the bootstrap `review` database user.
5. Change `.env` to `DATABASE_URL=postgresql+asyncpg://review_app:review_app_dev_only@localhost:5435/review_platform`.
6. Restart FastAPI: `uvicorn app.main:app --reload`.

## New endpoints
- `GET /api/v1/auth/organizations` — list organizations for the authenticated user.
- `POST /api/v1/auth/switch-organization` — issue a token for an organization where the user already has membership.

Existing login/register endpoints are updated for RLS context.

## Important
This patch is an intermediate security milestone, not a complete production security certification.
The RLS policy protects workspaces, projects and memberships. Organization/user tables,
admin provisioning, audit logs, SSO/MFA, rate limiting, password reset, and formal security
tests still need implementation. The starter Docker image creates `review` as a PostgreSQL bootstrap superuser, so the
application must NOT connect as `review` once RLS is enabled. The `create_app_role`
script creates `review_app` with NOSUPERUSER and NOBYPASSRLS; use that role in the
application DATABASE_URL. Keep the `review` role only for local administration.
Do not expose this development setup to external customers yet.
