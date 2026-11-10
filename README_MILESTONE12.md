# Milestone 12 — Java & Spring Boot Flow Intelligence

## New endpoints
- `GET /api/v1/knowledge/projects/{project_id}/java-flows?ref=main`
- `POST /api/v1/knowledge/projects/{project_id}/java-flow-impact`

Impact request:
```json
{"ref":"main","changed_paths":["src/main/java/com/acme/service/UserService.java"]}
```

The analyzer inventories Java classes, fields, method signatures, method calls, Spring REST mapping annotations, and references to DTO-like types. It infers calls through fields whose declared type matches another indexed class, helping trace controller/service/repository flows.

## Important limitations
This is heuristic static analysis, not Java compiler or bytecode analysis. It may miss Lombok-generated members, constructor-injected dependencies, interface-to-implementation bindings, overloaded method resolution, inherited methods, complex annotations, and calls hidden behind factories or reflection. Findings are evidence for review, not proof of runtime execution. No source is modified.
