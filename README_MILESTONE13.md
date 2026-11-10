# Milestone 13 — Intelligence-Enriched GitLab MR Reviews

This milestone connects the repository intelligence from Milestones 8–12 to the existing GitLab MR review workflow.

When `run_gitlab_review` reviews an MR, it now:
1. Parses the MR diff to identify changed paths.
2. Retrieves indexed source context, symbols, dependency hints, and project review rules.
3. Analyzes Java method flows and potential callers in the indexed target branch.
4. Searches other indexed repositories for references to changed Java types/packages.
5. Adds this evidence to the specialist review prompt.
6. Returns metrics describing how much repository intelligence was available.

The target branch is used for the local project architecture snapshot. Cross-project search scans indexed projects configured through `KNOWLEDGE_PROJECT_IDS`, plus the current project. If `KNOWLEDGE_PROJECT_IDS` is empty, cross-project analysis scans all projects in the shared knowledge database.

## Important operational requirement
Index all relevant service/library repositories into the same knowledge database before expecting cross-project context. For each project, use the existing index endpoint and build intelligence endpoint. The GitLab MR workflow does not silently clone or index every workspace repository.

## Review metadata
The `repository_context` result now includes Java files analyzed, method flows available, potential callers, cross-project findings, changed paths, and existing retrieval metrics.

## Limitations
Analysis is static and heuristic. It does not replace compiler-backed symbol resolution, runtime traces, full API schema comparison, or human validation. Findings are still constrained to changed-line locations by the review orchestrator, so contextual evidence informs findings but does not authorize comments on unchanged lines.
