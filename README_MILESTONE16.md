# Milestone 16 — Centralized Web + Remote Kiro MCP

## Architecture

One FastAPI backend and one shared review service now power:
- Browser UI at `/`
- Review API at `POST /api/v1/agent/review-merge-request`
- Remote MCP Streamable HTTP endpoint at `/mcp`
- Existing local stdio MCP server for local development

The web route and `review_gitlab_merge_request_url` MCP tool call the same
`app.services.mr_review_service.review_merge_request_url` function. GitLab
and AI credentials stay on the central server; clients only need an
`AGENT_ACCESS_TOKEN`.

## Server configuration

Configure the server `.env`:

```env
GITLAB_BASE_URL=https://oxford.infor.com
GITLAB_TOKEN=your_gitlab_read_token
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=your_ai_provider_key
AI_MODEL=gpt-4o-mini
AGENT_ACCESS_TOKEN=generate_a_long_random_secret
```

Generate a token locally with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Do not commit `.env`. Use HTTPS and an organization's approved secret store
for shared or production deployment. The agent access token is a shared
bearer secret in this milestone; use a separate token per environment and
rotate it if exposed. For production, put the service behind the company
reverse proxy/SSO and add per-user identity, audit logging, rate limits,
and secret rotation.

## Run centrally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
# Edit .env with real credentials and AGENT_ACCESS_TOKEN
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/` to use the browser interface. Other laptops
access `https://<internal-hostname>/` after the service is deployed behind
the organization's HTTPS reverse proxy or VPN. Do not expose port 8000
directly to the public internet.

## Remote Kiro MCP

The remote MCP endpoint is `https://<internal-hostname>/mcp`. Configure
Kiro's MCP server as a remote HTTP/Streamable HTTP server with:
- URL: `https://<internal-hostname>/mcp`
- Header: `Authorization: Bearer <AGENT_ACCESS_TOKEN>`

Example remote server entry (merge into the existing Kiro MCP configuration;
do not replace other configured servers):

```json
{
  "mcpServers": {
    "ai-code-review-agent": {
      "url": "https://<internal-hostname>/mcp",
      "headers": {
        "Authorization": "Bearer <AGENT_ACCESS_TOKEN>"
      }
    }
  }
}
```

Kiro's remote MCP configuration format can vary by version. Keep the
existing local stdio configuration as a fallback. The server also supports
local stdio via `python scripts/run_mcp_server.py`.

## Review safety

- Web and MCP review defaults to preview-only.
- Preview and publish modes both run the same full Java/Spring and cross-project
  review pipeline; preview mode simply skips GitLab writes.
- Publishing GitLab comments requires explicitly setting
  `publish_comments=true` in the API/MCP tool.
- The web page has an explicit publication checkbox; leave it unchecked
  for initial tests.
- The central server performs repository discovery/indexing. Each laptop
  uses the same server-side knowledge database, not a separate local copy.

## API

`POST /api/v1/agent/review-merge-request`

Header: `Authorization: Bearer <AGENT_ACCESS_TOKEN>`

Body:
```json
{
  "merge_request_url": "https://gitlab.example.com/group/project/-/merge_requests/123",
  "publish_comments": false,
  "min_confidence": 0.65,
  "max_workspace_projects": 20
}
```

`GET /health` remains a public liveness check. `/api/v1/agent/config`
and `/mcp` require the agent access token.
