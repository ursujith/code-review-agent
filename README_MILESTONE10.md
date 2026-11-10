# Milestone 10 — Spring Boot Architecture Intelligence

This milestone adds a first-pass Spring Boot architecture inventory to the existing repository knowledge store.

## New capabilities
- Detect Java packages, classes, interfaces, enums and records.
- Extract Spring MVC mapping annotations (`RequestMapping`, `GetMapping`, `PostMapping`, `PutMapping`, `PatchMapping`, `DeleteMapping`).
- Inventory JPA entities, fields and relationship annotations.
- Identify service-to-service client indicators such as `RestTemplate`, `WebClient`, `FeignClient`, `HttpClient` and `WebServiceTemplate`.
- Extract direct Maven and Gradle dependency declarations.
- Classify files into conventional controller/service/repository/entity/configuration/client layers.
- Produce evidence-based change-impact hotspots for changed endpoint/entity/client files.

## New API endpoints
- `GET /api/v1/knowledge/projects/{project_id}/spring-architecture?ref=main`
- `POST /api/v1/knowledge/projects/{project_id}/impact-analysis`

Example impact request:
```json
{
  "ref": "main",
  "changed_paths": [
    "src/main/java/com/acme/web/UserController.java"
  ]
}
```

## Usage
1. Index a repository using the existing `POST /api/v1/knowledge/projects/{project_id}/index` endpoint.
2. Build its existing symbol/import intelligence using `POST /api/v1/knowledge/projects/{project_id}/intelligence/build`.
3. Open Swagger at `/docs` and call the Spring architecture endpoint.
4. Submit changed paths to the impact-analysis endpoint.

## Limitations
This is intentionally a conservative first implementation. It uses source patterns, not a compiler-backed Java semantic model. It does not resolve Spring composed annotations, constants, runtime wiring, full method call graphs, transitive Maven/Gradle dependencies, database migrations, or downstream consumers across repositories. `cross_repository_impact` is explicitly marked `not_assessed`; do not treat heuristic hints as proof of a dependency. A later milestone should add JavaParser/JDT or build-tool integration and workspace-wide consumer mapping.
