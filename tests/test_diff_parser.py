from app.review.diff_parser import parse_git_diff


def test_parse_modified_file_and_line_numbers() -> None:
    diff = """diff --git a/example.py b/example.py
index 1234567..abcdefg 100644
--- a/example.py
+++ b/example.py
@@ -1,3 +1,4 @@
 def hello():
-    print("Hello")
+    print("Hello World")
+    return True
     """

    result = parse_git_diff(diff)

    assert result.total_files == 1
    assert result.total_added_lines == 2
    assert result.total_deleted_lines == 1
    file = result.files[0]
    assert file.old_path == "example.py"
    assert file.new_path == "example.py"
    assert file.change_type == "modified"
    assert file.added_lines[0].new_line_number == 2
    assert file.added_lines[1].new_line_number == 3
    assert file.deleted_lines[0].old_line_number == 2


def test_parse_added_file() -> None:
    diff = """diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+print('hello')
+print('world')
"""
    result = parse_git_diff(diff)
    assert result.total_files == 1
    assert result.files[0].change_type == "added"
    assert result.files[0].old_path is None
    assert result.files[0].new_path == "new.py"
    assert result.total_added_lines == 2


def test_parse_deleted_file() -> None:
    diff = """diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,1 +0,0 @@
-print('old')
"""
    result = parse_git_diff(diff)
    assert result.files[0].change_type == "deleted"
    assert result.files[0].old_path == "old.py"
    assert result.files[0].new_path is None
    assert result.total_deleted_lines == 1


def test_parse_multiple_files_and_binary_file() -> None:
    diff = """diff --git a/a.txt b/a.txt
--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-old
+new
diff --git a/image.png b/image.png
index 111..222 100644
Binary files a/image.png and b/image.png differ
"""
    result = parse_git_diff(diff)
    assert result.total_files == 2
    assert result.files[1].is_binary is True
    assert result.total_added_lines == 1
    assert result.total_deleted_lines == 1


def test_empty_diff() -> None:
    result = parse_git_diff("\n  ")
    assert result.files == []
    assert result.total_files == 0
