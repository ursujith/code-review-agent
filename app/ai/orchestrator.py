from __future__ import annotations

import asyncio
from collections import Counter
from typing import Iterable

from pydantic import ValidationError

from app.ai.agents.specialists import SPECIALISTS, Specialist, build_specialist_prompt
from app.ai.client import AIProviderError, OpenAICompatibleClient
from app.ai.reviewer import _validate_finding_locations
from app.ai.schemas import ReviewFinding
from app.review.diff_parser import parse_git_diff


_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_RISK_BY_SEVERITY = {"info": "none", "low": "low", "medium": "medium", "high": "high", "critical": "critical"}


class OrchestrationValidationError(ValueError):
    pass


async def _run_specialist(
    client: OpenAICompatibleClient,
    specialist: Specialist,
    user_prompt: str,
) -> tuple[str, list[ReviewFinding], str | None]:
    try:
        payload = await client.complete_json(
            f"Specialist: {specialist.name}\n{specialist.system_prompt}", user_prompt
        )
        raw_findings = payload.get("findings", [])
        if not isinstance(raw_findings, list):
            raise AIProviderError(f"{specialist.name} agent returned an invalid findings list")
        findings = [ReviewFinding.model_validate(item) for item in raw_findings]
        # Specialist scope is enforced server-side; a model cannot relabel its category.
        for finding in findings:
            finding.category = specialist.category
        return specialist.name, findings, None
    except ValidationError:
        return specialist.name, [], "invalid finding schema"
    except AIProviderError as exc:
        return specialist.name, [], str(exc)
    except Exception:
        # Keep one specialist failure from cancelling the other concurrent reviews.
        return specialist.name, [], "specialist execution failed"


def _aggregate(findings: Iterable[ReviewFinding], parsed_diff, min_confidence: float):
    location_valid, rejected_locations = _validate_finding_locations(list(findings), parsed_diff)
    by_key: dict[tuple[str, int, str], ReviewFinding] = {}
    rejected_confidence = 0
    for finding in location_valid:
        if finding.confidence < min_confidence:
            rejected_confidence += 1
            continue
        key = (finding.file_path, finding.line_number, finding.title.casefold().strip())
        existing = by_key.get(key)
        if existing is None or (
            finding.confidence,
            _SEVERITY_RANK[finding.severity],
        ) > (
            existing.confidence,
            _SEVERITY_RANK[existing.severity],
        ):
            by_key[key] = finding
    result = list(by_key.values())
    result.sort(key=lambda item: (-_SEVERITY_RANK[item.severity], -item.confidence, item.file_path, item.line_number))
    return result, rejected_locations + rejected_confidence, rejected_locations, rejected_confidence


async def run_multi_agent_review(
    client: OpenAICompatibleClient,
    diff_text: str,
    context: str | None = None,
    *,
    min_confidence: float = 0.65,
    specialists: tuple[Specialist, ...] = SPECIALISTS,
) -> dict:
    if not diff_text.strip():
        raise OrchestrationValidationError("diff_text cannot be empty")
    if len(diff_text) > 200_000:
        raise OrchestrationValidationError("diff_text exceeds the 200000 character limit")
    if context and len(context) > 200_000:
        raise OrchestrationValidationError("context exceeds the 200000 character limit")
    if not 0 <= min_confidence <= 1:
        raise OrchestrationValidationError("min_confidence must be between 0 and 1")
    if not specialists:
        raise OrchestrationValidationError("At least one specialist must be selected")

    parsed_diff = parse_git_diff(diff_text)
    if not parsed_diff.files:
        raise OrchestrationValidationError("No files were found in the supplied diff")

    prompt = build_specialist_prompt(diff_text, context)
    # Independent specialists run concurrently. A failed specialist is reported without
    # discarding successful results from the other specialists.
    outcomes = await asyncio.gather(
        *(_run_specialist(client, specialist, prompt) for specialist in specialists)
    )
    findings = [finding for _, batch, _ in outcomes for finding in batch]
    accepted, rejected, rejected_locations, rejected_confidence = _aggregate(
        findings, parsed_diff, min_confidence
    )
    highest = max((item.severity for item in accepted), key=lambda x: _SEVERITY_RANK[x], default="info")
    risk_level = _RISK_BY_SEVERITY[highest]
    failed_agents = [name for name, _, error in outcomes if error]
    successful_agents = [name for name, _, error in outcomes if not error]
    category_counts = Counter(item.category for item in accepted)

    return {
        "provider": "openai-compatible",
        "model": client.model,
        "overview": (
            f"Multi-agent review completed: {len(accepted)} actionable finding(s) accepted "
            f"from {len(successful_agents)} successful specialist(s)."
        ),
        "risk_level": risk_level,
        "findings": [item.model_dump(mode="json") for item in accepted],
        "metrics": {
            "reviewed_files": parsed_diff.total_files,
            "reviewed_added_lines": parsed_diff.total_added_lines,
            "raw_findings": len(findings),
            "accepted_findings": len(accepted),
            "rejected_findings": rejected,
            "rejected_invalid_locations": rejected_locations,
            "rejected_low_confidence": rejected_confidence,
            "findings_by_category": dict(category_counts),
        },
        "agents": {
            "successful": successful_agents,
            "failed": [{"name": name, "reason": error} for name, _, error in outcomes if error],
        },
        "partial": bool(failed_agents),
    }
