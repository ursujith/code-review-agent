from app import knowledge
from app.knowledge_intelligence import (
    build_intelligence, dependency_graph, extract_symbols_and_imports,
    hybrid_retrieve, search_symbols,
)


def test_python_ast_extracts_classes_functions_and_imports():
    symbols, imports = extract_symbols_and_imports(
        "service.py", "import os\nfrom app.models import User\nclass UserService:\n    def find_user(self, user_id):\n        return user_id\n"
    )
    assert {item["name"] for item in symbols} == {"UserService", "find_user"}
    assert "os" in imports
    assert "app.models" in imports


def test_intelligence_build_symbol_search_and_dependency_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "DB_PATH", tmp_path / "knowledge.db")
    conn = knowledge._connect()
    try:
        source = "from app.models import User\nclass UserService:\n    def find_user(self, user_id):\n        return user_id\n"
        conn.execute(
            "INSERT INTO code_chunks(project_id,project_name,ref,path,start_line,end_line,content,content_hash) VALUES(?,?,?,?,?,?,?,?)",
            ("p1", "group/service", "main", "service.py", 1, 4, source, "hash-1"),
        )
        conn.commit()
    finally:
        conn.close()

    result = build_intelligence("p1", "main")
    assert result["symbols_indexed"] == 2
    matches = search_symbols(["p1"], "find_user")
    assert matches and matches[0]["name"] == "find_user"
    graph = dependency_graph("p1", "main")
    assert any(edge["import"] == "app.models" for edge in graph["edges"])
    retrieved = hybrid_retrieve(["p1"], "UserService find_user", limit=3)
    assert retrieved["chunks"] == 1
    assert "UserService" in retrieved["context"]
    assert retrieved["retrieval"] == "bm25-symbol-hybrid"
