# Milestone 15 — Automatic GitLab workspace discovery from an MR URL

## What's new

- Added the Kiro MCP tool `review_gitlab_merge_request_url`.
- Pass a normal GitLab merge request URL; the tool resolves the project ID and MR IID through GitLab's API.
- It follows the project's group-parent chain to discover the top-level group path. No manually supplied `KNOWLEDGE_GROUP_ID` is required for this workflow.
- It discovers repositories in that group, including subgroups, and indexes up to the configured per-call limit (default 20, maximum 50) before reviewing.
- Individual repository indexing failures are recorded and do not stop the remaining repositories from being processed.
- Existing `review_gitlab_merge_request(project_id, merge_request_iid, ...)` and group-ID endpoints remain available for compatibility.

## Kiro usage

Select `review_gitlab_merge_request_url` and provide:

- `merge_request_url`: full HTTPS MR URL from the configured GitLab host
- `publish_comments`: false for preview (default), true to publish summary and inline comments
- `max_workspace_projects`: number of repositories to index on this call (default 20, max 50)

## Required `.env`

```env
GITLAB_BASE_URL=https://oxford.infor.com
GITLAB_TOKEN=your_gitlab_access_token
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=your_ai_provider_key
AI_MODEL=gpt-4o-mini
```

`KNOWLEDGE_GROUP_ID` is no longer required for the MR-URL workflow. Keep it only if you still want to use the older explicit group endpoints/workflow. The token needs permission to read the MR, project metadata, group hierarchy, repository tree, and repository files (`read_api` and `read_repository` where supported by your GitLab instance).

## Important behavior and limitations

- Only HTTPS URLs on the configured GitLab host are accepted. Do not include query parameters or access tokens in the URL.
- GitLab API access to the group hierarchy and repositories is required. Private or inaccessible repositories cannot be indexed.
- Indexing is synchronous and sequential in this milestone. Keep the limit modest (10–20) for initial runs; background workspace indexing is a future improvement.
- Repositories beyond the per-call limit are discovered but not indexed on that call.
- Preview mode includes retrieved cross-repository text context in the review, but the richer Java flow and cross-project impact context remains integrated in the existing published review workflow. This distinction will be unified in a later milestone.
- Static repository analysis is heuristic and should be validated; it is not a compiler or runtime call graph.
