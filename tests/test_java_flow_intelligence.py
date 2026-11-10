from app import knowledge
from app.java_flow_intelligence import analyze_java_flows, analyze_flow_impact


def test_java_flow_traces_controller_service_repository(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "DB_PATH", tmp_path / "flows.db")
    conn = knowledge._connect()
    samples = [
        ("src/main/java/com/acme/controller/UserController.java",
         "package com.acme.controller;\npublic class UserController {\n private UserService service;\n public UserDto getUser() { return service.findUser(); }\n}"),
        ("src/main/java/com/acme/service/UserService.java",
         "package com.acme.service;\npublic class UserService {\n private UserRepository repository;\n public UserDto findUser() { return repository.load(); }\n}"),
        ("src/main/java/com/acme/repository/UserRepository.java",
         "package com.acme.repository;\npublic class UserRepository {\n public UserDto load() { return new UserDto(); }\n}"),
        ("src/main/java/com/acme/dto/UserDto.java",
         "package com.acme.dto;\npublic class UserDto {\n private String name;\n}"),
    ]
    try:
        for path, content in samples:
            conn.execute("INSERT INTO code_chunks(project_id,project_name,ref,path,start_line,end_line,content,content_hash) VALUES(?,?,?,?,?,?,?,?)",
                         ("p1", "acme/app", "main", path, 1, len(content.splitlines()), content, path))
        conn.commit()
    finally:
        conn.close()
    result = analyze_java_flows("p1", "main")
    controller = [f for f in result["method_flows"] if f["class"] == "UserController" and f["method"] == "getUser"][0]
    assert any(c["target_class"] == "UserService" and c["method"] == "findUser" for c in controller["calls"])
    impact = analyze_flow_impact("p1", ["src/main/java/com/acme/service/UserService.java"], "main")
    assert any(x["class"] == "UserController" for x in impact["potential_callers"])
