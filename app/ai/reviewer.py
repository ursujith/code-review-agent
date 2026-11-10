from __future__ import annotations

from pydantic import ValidationError

from app.ai.client import AIProviderError, OpenAICompatibleClient
from app.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from app.ai.schemas import ReviewFinding, ReviewResult, ReviewSummary
from app.review.diff_parser import parse_git_diff


class ReviewValidationError(Exception):
    pass


def _validate_finding_locations(findings: list[ReviewFinding], parsed_diff) -> tuple[list[ReviewFinding], int]:
    added_locations: set[tuple[str, int]] = set()
    for file_diff in parsed_diff.files:
        path = file_diff.new_path or file_diff.old_path
        if not path:
            continue
        for line in file_diff.added_lines:
            if line.new_line_number is not None:
                added_locations.add((path.replace("\\", "/"), line.new_line_number))

    accepted: list[ReviewFinding] = []
    seen: set[tuple[str, int, str]] = set()
    rejected = 0
    for finding in findings:
        key = (finding.file_path, finding.line_number)
        if key not in added_locations:
            rejected += 1
            continue
        dedupe_key = (finding.file_path, finding.line_number, finding.title.casefold())
        if dedupe_key in seen:
            rejected += 1
            continue
        seen.add(dedupe_key)
        accepted.append(finding)
    return accepted, rejected


async def run_review(
    client: OpenAICompatibleClient,
    diff_text: str,
    context: str | None = None,
) -> ReviewResult:
    if not diff_text.strip():
        raise ReviewValidationError("diff_text cannot be empty")
    if len(diff_text) > 200_000:
        raise ReviewValidationError("diff_text exceeds the 200000 character limit")
    if context and len(context) > 200_000:
        raise ReviewValidationError("context exceeds the 200000 character limit")

    parsed_diff = parse_git_diff(diff_text)
    if not parsed_diff.files:
        raise ReviewValidationError("No files were found in the supplied diff")

    raw = await client.complete_json(SYSTEM_PROMPT, build_user_prompt(diff_text, context))
    try:
        summary = ReviewSummary.model_validate(raw)
    except ValidationError as exc:
        raise AIProviderError("AI provider response did not match the review schema") from exc

    accepted, rejected = _validate_finding_locations(summary.findings, parsed_diff)
    summary.findings = accepted
    if not accepted and summary.risk_level != "none":
        summary.risk_level = "none"
    return ReviewResult(
        model=client.model,
        summary=summary,
        accepted_findings=accepted,
        rejected_findings=rejected,
        reviewed_files=parsed_diff.total_files,
        reviewed_added_lines=parsed_diff.total_added_lines,
    )
