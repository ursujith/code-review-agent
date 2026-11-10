from pathlib import Path

import pytest

from app.review.context_builder import ContextBuildError, build_review_context
from app.review.diff_parser import parse_git_diff


def test_builds_source_window_around_added_line(tmp_path: Path) -> None:
    source = "\n".join(f"line {i}" for i in range(1, 31))
    (tmp_path / "sample.py").write_text(source, encoding="utf-8")
    diff = """diff --git a/sample.py b/sample.py
--- a/sample.py
+++ b/sample.py
@@ -10,2 +10,3 @@
 line 10
+new code
 line 11
"""
    result = build_review_context(parse_git_diff(diff), tmp_path, context_lines=2)
    file_context = result["files"][0]
    assert file_context["source_available"] is True
    window = file_context["source_windows"][0]
    assert window["start_line"] == 8
    assert window["end_line"] == 14
    assert "    10: line 10" in window["content"]


def test_rejects_path_traversal(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("secret", encoding="utf-8")
    diff = """diff --git a/../outside.py b/../outside.py
--- a/../outside.py
+++ b/../outside.py
@@ -1 +1 @@
-old
+new
"""
    result = build_review_context(parse_git_diff(diff), tmp_path)
    assert result["files"][0]["source_available"] is False


def test_rejects_invalid_repository_root() -> None:
    with pytest.raises(ContextBuildError, match="existing directory"):
        build_review_context(parse_git_diff("diff --git a/a b/a"), "not-a-real-repo-path")


def test_skips_binary_files(tmp_path: Path) -> None:
    (tmp_path / "image.bin").write_bytes(b"\x00\x01")
    diff = """diff --git a/image.bin b/image.bin
Binary files a/image.bin and b/image.bin differ
"""
    result = build_review_context(parse_git_diff(diff), tmp_path)
    assert result["files"][0]["is_binary"] is True
    assert result["files"][0]["source_available"] is False
