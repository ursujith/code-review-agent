# Connect the AI Code Review Agent to Kiro

This project exposes a local Model Context Protocol (MCP) server. It uses stdio, so it does not require a public URL or open network port.

## Tools

- `parse_diff`: parse a unified Git diff and summarize changed files and lines.
- `review_diff`: run the specialist AI reviewers on a supplied diff.
- `review_gitlab_merge_request`: fetch and review a GitLab MR. It is preview-only by default. `publish_comments=true` explicitly enables posting comments and a summary to GitLab.

## Windows setup

1. Merge this project into your existing project folder.
2. In PowerShell at the project root, install dependencies:

   ```powershell
   pip install -e "[dev]"
   ```

3. Set valid `AI_API_KEY`, `GITLAB_TOKEN`, and `GITLAB_BASE_URL` values in the project `.env` as needed. Never commit `.env`.
4. Run the Kiro setup helper:

   ```powershell
   .\scripts\configure_kiro_mcp.ps1
   ```

   It creates `.kiro/settings/mcp.json` using this project's `.venv` Python executable and preserves other MCP server entries.

5. Open the project folder in Kiro and ensure MCP support is enabled in Kiro settings.
6. Open Kiro's MCP panel and verify `ai-code-review-agent` is connected. If not, inspect the `Kiro - MCP Logs` output channel.

## Example Kiro prompts

- "Use parse_diff to summarize this unified diff: ..."
- "Use review_diff to review this diff. Focus on security and bugs: ..."
- "Review GitLab project 123, merge request 45 in preview mode."
- "Review GitLab project 123, merge request 45 and publish comments."

The last prompt writes to GitLab. Confirm the target project and MR before requesting publication.

## Security

- The MCP server runs locally as your Windows user and can read the project `.env`. Only connect it to a workspace you trust.
- Use a least-privilege GitLab token.
- Keep `publish_comments=false` unless you explicitly intend to write to GitLab.
- Do not auto-approve the publication tool.
- Do not expose the stdio MCP server publicly.
- AI findings are advisory and should be validated before merging.

## Background GitLab reviews (Milestone 7)

GitLab webhooks now enqueue review jobs instead of waiting for the AI review to finish. Redis stores job status and webhook idempotency keys; Celery workers execute the review workflow.

### Run locally on Windows

1. Install the updated dependencies in the project's virtual environment:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
   ```

2. Start Redis (for example, with Docker Desktop):

   ```powershell
   docker compose up -d redis
   ```

3. In a separate PowerShell terminal, start a worker:

   ```powershell
   .\.venv\Scripts\celery.exe -A app.jobs.celery_app:celery_app worker --loglevel=INFO --pool=solo --concurrency=1
   ```

   `--pool=solo` is the simplest option for local Windows development. For Linux/Docker, use the worker service in `docker-compose.yml` (default concurrency: 2).

4. Start the FastAPI application as usual:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
   ```

5. Configure the GitLab project webhook to call `POST /api/v1/webhooks/gitlab`, with the matching `X-Gitlab-Token` secret and Merge Request events enabled.

The webhook responds with HTTP `202` and a `job_id`. Poll `GET /api/v1/reviews/jobs/{job_id}` to read the job status (`queued`, `running`, `retrying`, `completed`, or `failed`) and the result when complete. Job status and idempotency records expire after seven days by default. Set `REVIEW_JOB_TTL_SECONDS` and `WEBHOOK_IDEMPOTENCY_TTL_SECONDS` to change those retention periods.

The webhook is idempotent for GitLab event UUIDs. If that header is absent, the service derives a stable key from the project, MR, action, state, and latest commit. Celery retries transient GitLab rate-limit/server errors and AI provider rate-limit/server errors; configure retry count and delay with `REVIEW_TASK_MAX_RETRIES` and `REVIEW_TASK_RETRY_DELAY_SECONDS`.

The Docker worker limits simultaneous reviews to two by default. Adjust `--concurrency` in the worker command to change this limit. Ensure the API and worker share the same Redis instance and have the same GitLab/AI environment variables.
