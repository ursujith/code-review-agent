from app import knowledge
from app.spring_architecture import analyze_spring_project, analyze_change_impact


def test_spring_architecture_extracts_endpoints_entities_and_layers(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "DB_PATH", tmp_path / "spring.db")
    conn = knowledge._connect()
    try:
        samples = [
            ("src/main/java/com/acme/web/UserController.java",
             """package com.acme.web;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping("/users")
public class UserController {
 @GetMapping("/{id}")
 public String getUser() { return "ok"; }
 @PostMapping
 public String createUser() { return "ok"; }
}
"""),
            ("src/main/java/com/acme/service/UserService.java",
             """package com.acme.service;
import org.springframework.web.client.RestTemplate;
@Service
public class UserService { private RestTemplate restTemplate; }
"""),
            ("src/main/java/com/acme/entity/User.java",
             """package com.acme.entity;
import jakarta.persistence.*;
@Entity
public class User {
 @Id private Long id;
 private String email;
 @ManyToOne private Account account;
}
"""),
        ]
        for path, content in samples:
            conn.execute(
                "INSERT INTO code_chunks(project_id,project_name,ref,path,start_line,end_line,content,content_hash) VALUES(?,?,?,?,?,?,?,?)",
                ("p1", "acme/app", "main", path, 1, len(content.splitlines()), content, path),
            )
        conn.commit()
    finally:
        conn.close()

    result = analyze_spring_project("p1", "main")
    assert result["java_files_analyzed"] == 3
    assert any(e["http_method"] == "GET" and e["path"] == "/users/{id}" for e in result["rest_endpoints"])
    assert len(result["jpa_entities"]) == 1
    assert "service" in result["layers"]
    assert result["service_clients"][0]["client_hints"] == ["RestTemplate"]


def test_change_impact_marks_endpoint_and_entity_files(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "DB_PATH", tmp_path / "impact.db")
    conn = knowledge._connect()
    try:
        source = """package com.acme.web;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping("/items")
public class ItemController {
 @DeleteMapping("/{id}")
 public void delete() {}
}
"""
        conn.execute(
            "INSERT INTO code_chunks(project_id,project_name,ref,path,start_line,end_line,content,content_hash) VALUES(?,?,?,?,?,?,?,?)",
            ("p1", "acme/app", "main", "src/main/java/com/acme/web/ItemController.java", 1, len(source.splitlines()), source, "x"),
        )
        conn.commit()
    finally:
        conn.close()
    result = analyze_change_impact("p1", ["src/main/java/com/acme/web/ItemController.java"], "main")
    assert result["potential_impacts"]
    assert "API compatibility" in result["potential_impacts"][0]["reason"]
    assert result["cross_repository_impact"] == "not_assessed"
