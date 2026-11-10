# Milestone 17 — Individual developer access and audit

Milestone 17 adds centrally managed, individual developer tokens while retaining the Milestone 16 shared token as a temporary compatibility path.

## Configure the administrator token

Generate a separate random administrator token:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Add it to the central server's `.env` file:

```env
AGENT_ADMIN_TOKEN=<generated-value>
AGENT_ACCESS_DB_PATH=./data/agent_access.sqlite3
```

Do not use the developer token or GitLab token as the administrator token. Restart the API after editing `.env`.

## Issue a developer token

Use the administrator token as a Bearer token:

```powershell
$admin = Read-Host "Administrator token"
$headers = @{ Authorization = "Bearer $admin" }
$body = @{ username = "developer.name" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/admin/agent-access/tokens -Headers $headers -ContentType "application/json" -Body $body
```

The response contains the developer token exactly once. Give it to that developer through an approved secure channel. The server stores only its SHA-256 hash; the plaintext cannot be retrieved later.

## List, revoke, and audit

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/admin/agent-access/tokens -Headers $headers
Invoke-RestMethod -Method Delete -Uri http://localhost:8000/api/v1/admin/agent-access/tokens/1 -Headers $headers
Invoke-RestMethod http://localhost:8000/api/v1/admin/agent-access/audit -Headers $headers
```

Replace `1` with the token ID returned by the list endpoint. Revocation takes effect on the next request.

## Developer usage

Each developer enters their own issued token in the web application's Agent access token field. Remote MCP clients use the same developer token in the `Authorization: Bearer ...` header. The old `AGENT_ACCESS_TOKEN` remains accepted for migration; remove it from `.env` once all developers have individual tokens.

## Audit scope and limitations

The web review endpoint records the authenticated username, MR URL, preview/publish mode, result status, and timestamp. Tokens are stored hashed. This milestone does not yet provide SSO, organization roles, per-user project permissions, token expiry, or audit export. The administrator token is a single high-privilege secret and must be protected accordingly.

Keep the access database in persistent storage and back it up. Use HTTPS behind your organization's trusted reverse proxy; do not expose the development server directly to the public internet.

## Verification

The Milestone 17 access-store and existing central-access tests pass. The complete suite could not be collected in the build environment because Celery is not installed there; webhook and queue tests therefore remain unverified in this packaging run. Install the project's development dependencies (`python -m pip install -e ".[dev]"`) before running the complete suite on the target machine.
