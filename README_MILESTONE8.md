# Milestone 8 — Repository Knowledge & Context-Aware Review

This milestone adds the first usable repository knowledge layer to the existing FastAPI, GitLab, Celery and Kiro MCP code-review agent.

## Capabilities

1. **Repository discovery:** list projects visible to the configured GitLab token under a GitLab group, including subgroup projects.
2. **Repository indexing:** fetch a selected project's repository tree and eligible text files at a branch/ref; split source into overlapping chunks and store them in a local SQLite knowledge index.
3. **RAG-style retrieval:** rank indexed chunks against MR title, description and diff terms, and pass selected source snippets into the existing multi-agent GitLab review workflow.
4. **Project review rules:** save and load bounded project-specific instructions, required checks and forbidden-pattern guidance. Rules are included in the review context.
5. **Architecture awareness (initial heuristic):** summarize top-level modules and imports found in indexed source chunks. This is a discovery aid, not a compiler-grade dependency graph.
6. **Review feedback:** record accepted/rejected finding decisions and report counts. Feedback is deliberately not used to auto-suppress findings or rewrite prompts; this avoids learning from unverified or malicious feedback.

## Configuration

Copy new settings from `.env.example` into `.env` as needed:

```dotenv
GITLAB_BASE_URL=https://oxford.infor.com
GITLAB_TOKEN=<read-only-token>
KNOWLEDGE_DB_PATH=./data/repository_knowledge.sqlite3
KNOWLEDGE_MAX_FILE_BYTES=250000
KNOWLEDGE_MAX_FILES=5000
KNOWLEDGE_PROJECT_IDS=123,456
REVIEW_RULES_DIR=./review-rules
```

Use a token with the minimum GitLab permissions needed to read the target group/projects (`read_api` and `read_repository`, subject to your GitLab policy). Do not commit `.env`, the SQLite index, or project rules. The group discovery endpoint only returns projects visible to the token; it cannot bypass GitLab permissions.

## API endpoints

All endpoints are under `/api/v1`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/knowledge/groups/{group_id}/projects` | Discover projects visible under a group |
| POST | `/knowledge/projects/{project_id}/index` | Index the default branch or supplied `{"ref":"branch-name"}` |
| POST | `/knowledge/context` | Retrieve relevant indexed chunks for a query |
| PUT | `/knowledge/projects/{project_id}/rules` | Save project-specific review rules |
| GET | `/knowledge/projects/{project_id}/rules` | Read project rules |
| GET | `/knowledge/projects/{project_id}/architecture` | Get heuristic module/import summary |
| POST | `/knowledge/projects/{project_id}/feedback` | Record accepted/rejected feedback |
| GET | `/knowledge/projects/{project_id}/feedback/summary` | Get feedback counts |

### Suggested setup flow

1. Start Redis and the Celery worker as in Milestone 7; start FastAPI locally.
2. Call `GET /api/v1/knowledge/groups/{group_id}/projects` to find project IDs. For your Infor GitLab instance, set `GITLAB_BASE_URL=https://oxford.infor.com`.
3. Call `POST /api/v1/knowledge/projects/{project_id}/index` for each repository you want indexed. You can index several accessible services/libraries individually.
4. Set `KNOWLEDGE_PROJECT_IDS` to comma-separated related project IDs (including the current project) in `.env`, then restart the API and worker so both processes load the setting.
5. Save project-specific rules with `PUT /api/v1/knowledge/projects/{project_id}/rules`.
6. Run a GitLab MR review. The workflow retrieves relevant chunks from the current project plus configured related projects and adds the project's rules to the AI review context.
7. Use the architecture and feedback endpoints to inspect relationships and feedback trends.

## Example project rules payload

```json
{
  "instructions": "Use constructor injection. Preserve existing API compatibility. Avoid logging credentials or personal data.",
  "required_checks": [
    "Validate all externally supplied input",
    "Add or update tests for changed behavior",
    "Check authorization at service boundaries"
  ],
  "forbidden_patterns": [
    "Hard-coded secrets",
    "System.out.println in production code"
  ],
  "severity_overrides": {}
}
```

## Important limitations and safety

- The index is a local SQLite prototype. It is not yet a distributed vector database and uses lexical relevance scoring, not embedding similarity. It is a practical first RAG retrieval baseline.
- Index each repository/ref explicitly. The index is a snapshot; re-index after branch changes. A future milestone should automate incremental indexing and pin cross-repository context to compatible commit SHAs.
- The architecture map is heuristic and currently strongest for language import statements. It does not prove runtime service calls or dependency direction.
- Feedback is stored for measurement only. Human-reviewed feedback should be curated before it influences prompts, ranking or policy.
- Treat repository content, comments and documentation as untrusted input. The model must not follow instructions embedded in source files that attempt to override review policy.
- The new knowledge endpoints do not add user authentication. Keep this service on a trusted developer network; do not expose it publicly. Protect GitLab tokens and restrict access at the network/API gateway layer.
- GitLab indexing reads repository files through the API and skips binary/oversized files and common generated/vendor directories. File count and size are configurable.

## Tests

Run:

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
```

The new tests cover retrieval project scoping, rule validation/round-trip and feedback recording. Live GitLab indexing and live LLM review require credentials and should be tested in your environment.
