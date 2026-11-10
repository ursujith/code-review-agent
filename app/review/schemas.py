from dataclasses import dataclass, field
from typing import Literal


LineType = Literal["added", "deleted", "context"]
ChangeType = Literal["added", "modified", "deleted", "renamed", "copied", "unknown"]


@dataclass(slots=True)
class ChangedLine:
    line_type: LineType
    content: str
    old_line_number: int | None = None
    new_line_number: int | None = None


@dataclass(slots=True)
class FileDiff:
    old_path: str | None
    new_path: str | None
    change_type: ChangeType = "modified"
    lines: list[ChangedLine] = field(default_factory=list)
    is_binary: bool = False

    @property
    def added_lines(self) -> list[ChangedLine]:
        return [line for line in self.lines if line.line_type == "added"]

    @property
    def deleted_lines(self) -> list[ChangedLine]:
        return [line for line in self.lines if line.line_type == "deleted"]


@dataclass(slots=True)
class ParsedDiff:
    files: list[FileDiff]

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def total_added_lines(self) -> int:
        return sum(len(file.added_lines) for file in self.files)

    @property
    def total_deleted_lines(self) -> int:
        return sum(len(file.deleted_lines) for file in self.files)
