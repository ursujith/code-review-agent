# AI Code Review Agent – Milestone 2

This version builds the first two preparation stages of the code-review workflow. Authentication,
user registration, organization management, and workspace management are intentionally out of scope.

## Implemented

### Milestone 1 – Diff extraction
- Parse unified Git diffs.
- Extract changed file paths, change types, binary markers, added/deleted/context lines, and old/new line numbers.
- API: `POST /api/v1/reviews/parse-diff`.

### Milestone 2 – Review context builder
- Read changed files from a local repository checkout.
- Collect bounded source windows around changed lines, including surrounding context.
- Preserve deleted-line snippets from the diff because deleted code is not present in the current checkout.
- Skip binary, missing, non-UTF-8, excluded-directory, and oversized source files.
- Reject path traversal and symlink escapes outside the repository root.
- Apply limits to context window size, file count, file size, and total context characters.
- API: `POST /api/v1/reviews/build-context`.

## Requirements

- Python 3.11 or newer
- PowerShell on Windows (commands below use PowerShell syntax)

The current milestones do not require PostgreSQL, Redis, or an AI API key. Docker services are retained
for later milestones but do not need to be started for these endpoints.

## Setup

From the project root, with your virtual environment activated:

```powershell
pip install -e "[dev]"
```

## Run tests

```powershell
python -m pytest tests -v
```

## Start the API

```powershell
uvicorn app.main:app --reload
```

Swagger UI: <http://localhost:8000/docs>

## Build review context

Use `POST /api/v1/reviews/build-context` in Swagger. Example request:

```json
{
  "diff_text": "diff --git a/example.py b/example.py\\n--- a/example.py\\n+++ b/example.py\\n@@ -1,2 +1,2 @@\\n def run():\\n-    return False\\n+    return True\\n",
  "repository_root": "C:/work/my-repository",
  "context_lines": 12,
  "max_context_chars": 100000
}
```

`repository_root` must point to a local checkout visible to the API process. The response includes
one entry per changed file, source windows with line numbers, and deleted-line snippets.

**Security note:** This endpoint accepts a filesystem path and is intended only for local development.
Do not expose it to untrusted clients or the public internet. In production, a trusted Git-provider
adapter should create an isolated worker checkout and pass that controlled path to the context builder.

## Next milestones

1. Git provider adapter: fetch merge request metadata, diffs, and base/head revisions from GitLab first.
2. Repository context improvements: symbol extraction, language-aware parsing, and base-commit context.
3. AI review orchestration: correctness, security, performance, and maintainability analysis.
4. Finding validation, evidence checks, severity/confidence scoring, and deduplication.
5. Publish inline comments and a review summary back to the Git provider.


## Milestone 3: GitLab merge request integration

This milestone adds a read-only GitLab provider client. It retrieves merge request
metadata and changed-file diffs, converts GitLab's per-file diff payload into a
unified diff, and returns a compact diff summary.

### Configuration

Copy `.env.example` to `.env` and configure:

```dotenv
GITLAB_BASE_URL=https://gitlab.com
GITLAB_TOKEN=your_read_api_token
```

For a self-managed GitLab instance, set `GITLAB_BASE_URL` to its trusted base URL.
The token should have only the permissions required to read project and merge
request data (typically `read_api` and repository read access). Do not commit `.env`,
put tokens in URLs, or expose this development endpoint publicly. In production,
store provider tokens in a secrets manager and resolve them server-side per repo.

### Fetch a merge request

Start the API and call:

```http
GET /api/v1/providers/gitlab/projects/{project_id}/merge-requests/{merge_request_iid}
PRIVATE-TOKEN: <your-token>
```

`project_id` may be a numeric project ID or a URL-encoded namespace/project path.
The endpoint returns merge request metadata, changed-file records, a unified
`diff_text`, and totals for files/added/deleted lines. The token can instead be
configured in `GITLAB_TOKEN` for local development.

### Current limitations

- This integration is read-only; it does not post review comments.
- GitLab may omit diffs for binary or oversized files. Those files remain in the
  `changes` metadata but cannot contribute line-level diff content.
- Repository checkout and context extraction are still separate steps. Do not
  expose arbitrary local filesystem paths through a public API.
- The GitLab base URL is configuration, not a request parameter, to avoid an
  untrusted caller selecting arbitrary outbound destinations.

### Tests

```powershell
pip install -e ".[dev]"
python -m pytest tests -v
```

## Milestone 4: AI review engine

This milestone adds an AI-powered review endpoint using any provider that supports the
OpenAI Chat Completions request/response format. The endpoint sends the unified diff and
optional repository context to the configured model, validates the returned JSON, and
accepts findings only when they point to an added line in the supplied diff. Duplicate
findings at the same file/line/title are removed.

### Configure an AI provider

Copy `.env.example` to `.env` and set:

```dotenv
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=your_provider_api_key
AI_MODEL=gpt-4o-mini
```

`AI_BASE_URL` should be the provider's API base URL (the client appends
`/chat/completions`). Keep the key in `.env` for local development only; never commit it.
The application loads `.env` at startup. Restart Uvicorn after changing these values.

### Run an AI review

Call `POST /api/v1/reviews/analyze` from Swagger with:

```json
{
  "diff_text": "diff --git a/example.py b/example.py\\n--- a/example.py\\n+++ b/example.py\\n@@ -1,2 +1,2 @@\\n def run():\\n-    return False\\n+    return True\\n",
  "context": "Optional relevant source context from the repository checkout."
}
```

The response includes a concise overview, overall risk level, accepted findings, number of
rejected findings, and review coverage counts. Each finding contains a changed file path,
new line number, severity, category, explanation, recommendation, evidence, and confidence.

### Review safeguards and limitations

- Repository content is explicitly treated as untrusted data in the review prompt to reduce
  prompt-injection risk. This is a defense-in-depth measure, not a guarantee.
- Findings are accepted only if their file and line point to an added line in the diff.
  This filters invalid locations but does not independently prove that the finding is true.
- The model response is schema-validated and duplicate findings are removed.
- Input diff and context are each limited to 200,000 characters.
- The endpoint currently runs synchronously and is intended for development/small reviews.
  Large reviews should move to a background worker with provider retries, token budgeting,
  per-tenant quotas, audit logging, and cancellation.
- Do not send secrets or sensitive source code to an external model unless your organization's
  data-handling policy permits it. Configure an approved provider or private endpoint.

### Tests

```powershell
pip install -e ".[dev]"
python -m pytest tests -v
```

## Milestone 5: Parallel specialist review orchestration

The `POST /api/v1/reviews/orchestrate` endpoint runs up to four independent review
specialists concurrently: bug, security, performance, and maintainability/testing.
Each specialist returns structured findings. The orchestration layer then:

- enforces each specialist's assigned finding category;
- accepts findings only when their file and line point to an added line in the diff;
- filters findings below the configurable confidence threshold (default `0.65`);
- removes duplicate findings and orders the remaining findings by severity/confidence;
- calculates an overall risk level and reports per-agent success/failure status.

Example request:

```json
{
  "diff_text": "diff --git a/example.py b/example.py\\n--- a/example.py\\n+++ b/example.py\\n@@ -1,1 +1,2 @@\\n+password = 'example'\\n",
  "context": "Optional repository context",
  "min_confidence": 0.7,
  "agents": ["bug", "security", "performance", "maintainability"]
}
```

`agents` is optional; omitting it runs all specialists. A failed specialist is reported
in `agents.failed` without discarding results from successful specialists. The response
contains `partial`, `metrics`, `risk_level`, and the validated `findings` list.

The current implementation makes one model request per specialist in parallel. Configure
`AI_API_KEY`, `AI_BASE_URL`, and `AI_MODEL` in `.env`. Provider usage and latency therefore
increase with the number of selected specialists. Tests use mocked model responses and do
not require a live API key.

Run the test suite with:

```powershell
python -m pytest tests -v
```

## Milestone 6: GitLab webhook-driven review and publication

This milestone connects the GitLab provider, multi-agent reviewer, and GitLab write APIs
into one end-to-end flow. Configure a GitLab project webhook for **Merge request events**
with the URL `https://<your-host>/api/v1/webhooks/gitlab`. Set the webhook Secret Token
in GitLab to the same value as `GITLAB_WEBHOOK_SECRET` in the service environment.

Required environment variables:

```dotenv
GITLAB_BASE_URL=https://gitlab.com
GITLAB_TOKEN=your_project_or_bot_token
GITLAB_WEBHOOK_SECRET=a_long_random_webhook_secret
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=your_ai_provider_key
AI_MODEL=gpt-4o-mini
```

The GitLab token must be allowed to read merge requests and create merge request notes
and discussions (for GitLab.com, use the narrowest token type/scopes permitted by your
organization, typically API access). Keep credentials in a secret manager in deployed
environments; never commit `.env`.

The webhook validates `X-Gitlab-Token` using a constant-time comparison, accepts only
merge-request `open`, `reopen`, and `update` events while the MR is open, fetches the MR
and its diff, runs the specialist orchestrator, publishes line comments as GitLab
Discussions when diff revision SHAs are available, and publishes a summary Note. The
response reports successful inline publications, skipped comments, and publication
warnings. If GitLab does not provide all three diff revision SHAs, inline comments are
skipped but the summary can still be published.

### Local webhook testing

GitLab cannot reach `localhost` on your machine. For local end-to-end testing, expose
port 8000 through an approved secure tunnel, or first test the route with a mocked
webhook request. Do not expose the development server directly to the public internet.

### Important production limitations

- This first webhook workflow runs synchronously in the request. GitLab may retry or
  time out on larger merge requests. The next milestone should move work to a durable
  background queue and acknowledge the webhook quickly.
- Delivery idempotency is not yet persisted. Before production, add Redis/database-backed
  deduplication using GitLab's `X-Gitlab-Event-UUID`, with a durable job state and retry policy.
- This milestone uses one configured GitLab token and one configured AI provider key.
  Multi-project installations need a secure per-repository credential resolver.
- Repository checkout/context retrieval is not yet wired into this webhook path; reviews
  currently analyze the MR diff. Add isolated checkout and context retrieval in a worker.
- AI findings are suggestions, not proof. Require human review before merging and do not
  automatically approve or merge code.

### Tests

```powershell
python -m pytest tests -v
```


## Latest implementation

See `README_MILESTONE16.md` for centralized web access and remote Kiro MCP deployment.
