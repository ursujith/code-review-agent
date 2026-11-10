"""Build bounded source context around changed lines from a local repository checkout."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from app.review.schemas import FileDiff, ParsedDiff

DEFAULT_CONTEXT_LINES = 12
MAX_SOURCE_FILE_BYTES = 1_000_000
MAX_CONTEXT_CHARS = 100_000
MAX_FILES = 100
EXCLUDED_PARTS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    ".idea", ".pytest_cache", "target",
}


class ContextBuildError(ValueError):
    """Raised when repository context cannot safely be collected."""


def _safe_file_path(root: Path, relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if any(part in EXCLUDED_PARTS for part in candidate.relative_to(root).parts):
        return None
    return candidate


def _merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1] + 1:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _changed_ranges(file_diff: FileDiff, total_lines: int, context_lines: int) -> list[tuple[int, int]]:
    changed_numbers = [
        line.new_line_number
        for line in file_diff.lines
        if line.line_type in {"added", "context"} and line.new_line_number is not None
    ]
    if not changed_numbers:
        # Deleted-only changes have no corresponding current line. Include a small
        # beginning-of-file excerpt and retain the deleted code in the diff section.
        return [(1, min(total_lines, max(1, context_lines * 2 + 1)))] if total_lines else []
    ranges = [
        (max(1, number - context_lines), min(total_lines, number + context_lines))
        for number in changed_numbers
        if total_lines
    ]
    return _merge_ranges(ranges)


def build_review_context(
    parsed_diff: ParsedDiff,
    repository_root: str | Path,
    context_lines: int = DEFAULT_CONTEXT_LINES,
    max_context_chars: int = MAX_CONTEXT_CHARS,
) -> dict:
    """Collect changed-file source windows and diff snippets from a checkout.

    Paths are resolved and constrained to repository_root. This reads the current
    checkout only; for deleted/renamed old-side content, the diff remains the source
    of truth until a Git-provider adapter can fetch the base commit.
    """
    if context_lines < 0 or context_lines > 100:
        raise ContextBuildError("context_lines must be between 0 and 100")
    if max_context_chars < 1 or max_context_chars > MAX_CONTEXT_CHARS:
        raise ContextBuildError(f"max_context_chars must be between 1 and {MAX_CONTEXT_CHARS}")

    root = Path(repository_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ContextBuildError("repository_root must be an existing directory")
    if len(parsed_diff.files) > MAX_FILES:
        raise ContextBuildError(f"Diff contains more than {MAX_FILES} files")

    results: list[dict] = []
    remaining = max_context_chars
    for file_diff in parsed_diff.files:
        path = _safe_file_path(root, file_diff.new_path)
        entry = {
            "old_path": file_diff.old_path,
            "new_path": file_diff.new_path,
            "change_type": file_diff.change_type,
            "is_binary": file_diff.is_binary,
            "source_available": False,
            "source_windows": [],
            "deleted_lines": [
                {"line_number": line.old_line_number, "content": line.content}
                for line in file_diff.deleted_lines
            ],
        }
        if path is None or file_diff.is_binary or not path.is_file():
            results.append(entry)
            continue
        if path.stat().st_size > MAX_SOURCE_FILE_BYTES:
            entry["source_skipped_reason"] = "source file exceeds 1 MB limit"
            results.append(entry)
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            entry["source_skipped_reason"] = "source file is not readable UTF-8 text"
            results.append(entry)
            continue

        source_lines = source.splitlines()
        entry["source_available"] = True
        for start, end in _changed_ranges(file_diff, len(source_lines), context_lines):
            if remaining <= 0:
                entry["source_truncated"] = True
                break
            numbered = "\n".join(
                f"{number:>6}: {source_lines[number - 1]}"
                for number in range(start, end + 1)
            )
            numbered = numbered[:remaining]
            if numbered:
                entry["source_windows"].append({
                    "start_line": start,
                    "end_line": min(end, start + numbered.count("\n")),
                    "content": numbered,
                })
                remaining -= len(numbered)
            if len(numbered) < sum(len(source_lines[i - 1]) + 8 for i in range(start, end + 1)):
                entry["source_truncated"] = True
                break
        results.append(entry)

    return {
        "repository_root": str(root),
        "total_files": len(results),
        "context_characters_remaining": remaining,
        "files": results,
    }
