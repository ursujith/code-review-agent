# Milestone 14 — GitLab Workspace Auto-Indexing

Version: **1.6.0**

## What is new

- Discover projects in a GitLab group, including subgroups.
- Index a bounded batch of repositories from one API request.
- Continue processing when an individual repository fails.
- Persist group-to-project mapping, indexing state, timestamps, and last result in the shared SQLite knowledge database.
- Skip projects already indexed unless `force=true` or an explicit `ref` is supplied.
- Automatically include indexed workspace repositories in GitLab MR review retrieval and cross-project impact analysis.
- Record indexed refs and fall back to an available indexed ref when the MR target branch is not indexed. The review response exposes `analysis_ref` and `target_ref_fallback_used`.

## Configuration

Keep the GitLab token local in `.env`:

```dotenv
GITLAB_BASE_URL=https://oxford.infor.com
GITLAB_TOKEN=your_personal_access_token
KNOWLEDGE_GROUP_ID=your_gitlab_group_id
```

`GITLAB_URL` is also accepted as an alias for `GITLAB_BASE_URL`.

The token needs read access to the group and repositories (typically `read_api` and `read_repository`). Never commit the token.

`KNOWLEDGE_GROUP_ID` tells MR reviews which indexed group membership to use automatically. `KNOWLEDGE_PROJECT_IDS` remains supported as an optional comma-separated supplement.

## API usage

### 1. Discover projects

```http
GET /api/v1/knowledge/groups/{group_id}/projects
```

### 2. Index a workspace batch

```http
POST /api/v1/knowledge/groups/{group_id}/index
Content-Type: application/json

{
  "max_projects": 20,
  "force": false
}
```

Optional `ref` selects a branch/ref for all selected projects:

```json
{
  "max_projects": 10,
  "ref": "main",
  "force": true
}
```

- `max_projects`: 1–50; default 20. Run multiple batches for larger groups.
- `force`: re-index projects that were already indexed.
- `ref`: explicitly index the requested ref; this also bypasses the already-indexed skip.
- A project failure is reported in its result and does not stop the remaining projects.
- The endpoint runs sequentially in the API request. For large groups, use small batches; background orchestration is a future improvement.

### 3. Check indexing status

```http
GET /api/v1/knowledge/groups/{group_id}/index-status
```

The response includes total, indexed, failed, and discovered counts, plus per-project details.

### 4. Review an MR

After workspace indexing, the existing GitLab MR review endpoint automatically considers indexed repositories for the configured `KNOWLEDGE_GROUP_ID`. The review metadata includes:

- `workspace_projects_considered`
- `indexed_refs`
- `analysis_ref`
- `target_ref_fallback_used`

## Storage and limitations

- Workspace metadata and source chunks are stored in the configured `KNOWLEDGE_DB_PATH` SQLite database. Use the same shared database for the API and worker.
- Indexing is sequential and request-bound in this milestone; very large groups may exceed reverse-proxy/request timeouts. Index in batches.
- Group discovery uses GitLab's group projects API with subgroup inclusion and excludes shared projects.
- A user token can only discover and read projects the token owner can access.
- Static cross-service and Java-flow analysis remains heuristic. Indexing more repositories increases available evidence but does not guarantee complete dependency discovery.
- Indexing is per selected ref. MR review reports when it had to use another indexed ref instead of the target branch.

## Validation

Added `tests/test_workspace_indexing.py` for workspace status persistence, indexed-ref lookup, and resilient batch processing.

Test command:

```powershell
python -m pytest tests/test_knowledge.py tests/test_knowledge_intelligence.py tests/test_spring_architecture.py tests/test_cross_service_intelligence.py tests/test_java_flow_intelligence.py tests/test_gitlab_client.py tests/test_gitlab_publication.py tests/test_gitlab_api.py tests/test_workspace_indexing.py -v
```
