from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_parse_diff_endpoint() -> None:
    response = client.post(
        "/api/v1/reviews/parse-diff",
        json={
            "diff_text": """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1,2 @@
-old()
+new()
+extra()
"""
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_files"] == 1
    assert body["total_added_lines"] == 2
    assert body["total_deleted_lines"] == 1
    assert body["files"][0]["new_path"] == "a.py"


def test_build_context_endpoint(tmp_path):
    (tmp_path / "app.py").write_text("def run():\n    return True\n", encoding="utf-8")
    response = client.post(
        "/api/v1/reviews/build-context",
        json={
            "diff_text": "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def run():\n-    return False\n+    return True\n",
            "repository_root": str(tmp_path),
            "context_lines": 1,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_files"] == 1
    assert body["files"][0]["source_available"] is True
    assert "return True" in body["files"][0]["source_windows"][0]["content"]
