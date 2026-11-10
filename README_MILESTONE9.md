# Milestone 9 — AST-aware Repository Intelligence and Hybrid Retrieval

This milestone extends Milestone 8 with symbol indexing, dependency/import extraction, and BM25-style retrieval boosted by symbol and path matches.

## What is included

- Python source is parsed with the standard-library `ast` module to extract classes and functions with line ranges.
- Other languages use conservative declaration/import patterns. These are heuristics, not a full compiler or type-resolved call graph.
- Extracted symbols and imports are stored in SQLite, scoped by project and Git ref.
- Context retrieval now uses BM25-style term weighting, with additional boosts for path and symbol matches.
- GitLab MR review context includes retrieved code, symbol references, and import relationships.
- New API endpoints build intelligence, search symbols, and return the heuristic dependency graph.

## New API endpoints

- `POST /api/v1/knowledge/projects/{project_id}/intelligence/build` with optional `{"ref":"main"}`
- `GET /api/v1/knowledge/projects/{project_id}/symbols?query=AuthenticationService&limit=30`
- `GET /api/v1/knowledge/projects/{project_id}/dependencies?ref=main`
- `POST /api/v1/knowledge/context` now uses BM25-symbol hybrid retrieval.

## Important limitations

This is not yet embedding-based vector RAG. BM25-style lexical retrieval and symbol matching provide a stronger baseline without an external embedding model or vector database. Python parsing is AST-based; Java/JavaScript/TypeScript and other languages use best-effort regex extraction. Import edges are heuristic and do not prove runtime dependencies or call relationships.

## Recommended sequence

1. Index a repository at a pinned branch/ref.
2. Build repository intelligence for that same ref.
3. Search symbols and inspect dependency output.
4. Run an MR review and inspect `repository_context` sources.
5. Add a proper embedding provider/vector store and language-specific parsers in a later milestone.
