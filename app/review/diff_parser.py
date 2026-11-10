"""Parser for unified Git diffs (including the format returned by GitLab)."""

from __future__ import annotations

import re
from typing import Final

from app.review.schemas import ChangedLine, FileDiff, ParsedDiff

_HUNK_RE: Final[re.Pattern[str]] = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
)


def _clean_path(raw_path: str, prefix: str) -> str | None:
    """Remove Git's a/ or b/ prefix; /dev/null represents a missing side."""
    path = raw_path.strip()
    if path == "/dev/null":
        return None
    if path.startswith(prefix):
        path = path[len(prefix) :]
    return path


def parse_git_diff(diff_text: str) -> ParsedDiff:
    """Convert a unified diff string into file and line-level structures.

    The parser tracks line numbers on both sides of each hunk. It intentionally
    ignores file metadata outside hunks and binary payloads, while retaining
    binary-file information in the resulting FileDiff.
    """
    if not diff_text or not diff_text.strip():
        return ParsedDiff(files=[])

    files: list[FileDiff] = []
    current: FileDiff | None = None
    old_line: int | None = None
    new_line: int | None = None
    in_hunk = False

    def finish_current() -> None:
        if current is not None:
            files.append(current)

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            finish_current()
            current = FileDiff(old_path=None, new_path=None)
            old_line = new_line = None
            in_hunk = False
            continue

        if current is None:
            continue

        if line.startswith("new file mode "):
            current.change_type = "added"
            continue
        if line.startswith("deleted file mode "):
            current.change_type = "deleted"
            continue
        if line.startswith("rename from "):
            current.change_type = "renamed"
            current.old_path = line[len("rename from ") :]
            continue
        if line.startswith("rename to "):
            current.change_type = "renamed"
            current.new_path = line[len("rename to ") :]
            continue
        if line.startswith("copy from "):
            current.change_type = "copied"
            current.old_path = line[len("copy from ") :]
            continue
        if line.startswith("copy to "):
            current.change_type = "copied"
            current.new_path = line[len("copy to ") :]
            continue
        if line.startswith("Binary files ") or line == "GIT binary patch":
            current.is_binary = True
            in_hunk = False
            continue
        if line.startswith("--- "):
            current.old_path = _clean_path(line[4:], "a/")
            continue
        if line.startswith("+++ "):
            current.new_path = _clean_path(line[4:], "b/")
            continue

        match = _HUNK_RE.match(line)
        if match:
            old_line = int(match.group(1))
            new_line = int(match.group(3))
            in_hunk = True
            continue

        if not in_hunk:
            continue
        if line.startswith("\\ No newline at end of file"):
            continue

        if line.startswith("+"):
            current.lines.append(
                ChangedLine("added", line[1:], new_line_number=new_line)
            )
            if new_line is not None:
                new_line += 1
        elif line.startswith("-"):
            current.lines.append(
                ChangedLine("deleted", line[1:], old_line_number=old_line)
            )
            if old_line is not None:
                old_line += 1
        elif line.startswith(" "):
            current.lines.append(
                ChangedLine(
                    "context",
                    line[1:],
                    old_line_number=old_line,
                    new_line_number=new_line,
                )
            )
            if old_line is not None:
                old_line += 1
            if new_line is not None:
                new_line += 1
        else:
            # A line outside the unified-diff markers ends the current hunk.
            in_hunk = False

    finish_current()
    return ParsedDiff(files=files)
