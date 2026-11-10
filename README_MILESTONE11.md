# Milestone 11 — Cross-Service Intelligence

This milestone adds static cross-project analysis over repositories already indexed in the shared knowledge database.

## Before using it
1. Configure `GITLAB_TOKEN` locally in `.env` with `read_api` and `read_repository`.
2. Configure `GITLAB_BASE_URL=https://oxford.infor.com` (or `GITLAB_URL`).
3. Discover the GitLab group using `GET /api/v1/knowledge/groups/{group_id}/projects`.
4. Index each relevant project using `POST /api/v1/knowledge/projects/{project_id}/index` and optionally build symbol intelligence using `POST /api/v1/knowledge/projects/{project_id}/intelligence/build`.

Indexing is per project/ref. Cross-project analysis only sees content that has been indexed into the same knowledge database.

## New endpoints

- `GET /api/v1/knowledge/workspace-architecture`
  Lists indexed projects, refs, Java file counts, build coordinates, and inferred dependency edges.
- `POST /api/v1/knowledge/projects/{project_id}/cross-project-impact`
  Request:
  ```json
  {
    "ref": "main",
    "changed_paths": ["src/main/java/com/acme/shared/UserDto.java"],
    "candidate_project_ids": []
  }
  ```
  Empty `candidate_project_ids` scans all other indexed projects. A supplied list limits the scan.

## Evidence and limitations

- Exact imports of a changed Java type are reported as high-confidence source references.
- Package prefix matches and build-coordinate hints are medium confidence.
- Feign client presence is a low-confidence manual-review hint; it is not treated as proof of a provider/consumer relationship.
- This is regex-based static analysis, not Java compiler symbol resolution. It does not resolve transitive Maven/Gradle dependencies, runtime calls, generated code, or fully compare OpenAPI contracts.
- Only indexed projects and refs are considered. Indexing a GitLab group does not automatically index all repositories; call the index endpoint for each repository.

The GitLab token is never stored in the database by this feature. Keep it in the local `.env` file and do not commit it.
