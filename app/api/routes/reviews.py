from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.review.diff_parser import parse_git_diff
from app.review.context_builder import ContextBuildError, build_review_context

router = APIRouter(prefix="/reviews", tags=["code review"])


class ParseDiffRequest(BaseModel):
    diff_text: str = Field(min_length=1, description="Unified Git diff text")


class ChangedLineResponse(BaseModel):
    line_type: str
    content: str
    old_line_number: int | None = None
    new_line_number: int | None = None


class FileDiffResponse(BaseModel):
    old_path: str | None
    new_path: str | None
    change_type: str
    is_binary: bool
    lines: list[ChangedLineResponse]


class ParseDiffResponse(BaseModel):
    total_files: int
    total_added_lines: int
    total_deleted_lines: int
    files: list[FileDiffResponse]


@router.post("/parse-diff", response_model=ParseDiffResponse)
async def parse_diff(request: ParseDiffRequest) -> ParseDiffResponse:
    parsed = parse_git_diff(request.diff_text)
    return ParseDiffResponse(
        total_files=parsed.total_files,
        total_added_lines=parsed.total_added_lines,
        total_deleted_lines=parsed.total_deleted_lines,
        files=[
            FileDiffResponse(
                old_path=file.old_path,
                new_path=file.new_path,
                change_type=file.change_type,
                is_binary=file.is_binary,
                lines=[
                    ChangedLineResponse(
                        line_type=line.line_type,
                        content=line.content,
                        old_line_number=line.old_line_number,
                        new_line_number=line.new_line_number,
                    )
                    for line in file.lines
                ],
            )
            for file in parsed.files
        ],
    )


class BuildContextRequest(BaseModel):
    diff_text: str = Field(min_length=1, description="Unified Git diff text")
    repository_root: str = Field(min_length=1, description="Path to a local repository checkout")
    context_lines: int = Field(default=12, ge=0, le=100)
    max_context_chars: int = Field(default=100000, ge=1, le=100000)


@router.post("/build-context")
async def build_context(request: BuildContextRequest) -> dict:
    """Build source windows around changed lines from a local checkout.

    This endpoint is intended for local development. Do not expose arbitrary
    filesystem path access publicly; production integrations should resolve
    repositories in an isolated worker from a trusted provider checkout.
    """
    parsed = parse_git_diff(request.diff_text)
    try:
        return build_review_context(
            parsed,
            request.repository_root,
            context_lines=request.context_lines,
            max_context_chars=request.max_context_chars,
        )
    except ContextBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class AnalyzeReviewRequest(BaseModel):
    diff_text: str = Field(min_length=1, max_length=200000)
    context: str | None = Field(default=None, max_length=200000)


@router.post("/analyze")
async def analyze_review(request: AnalyzeReviewRequest) -> dict:
    """Run an AI review using the configured OpenAI-compatible provider."""
    import os

    from app.ai.client import AIProviderError, OpenAICompatibleClient
    from app.ai.reviewer import ReviewValidationError, run_review

    api_key = os.getenv("AI_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="AI provider is not configured. Set AI_API_KEY in the environment.",
        )

    client = OpenAICompatibleClient(
        base_url=os.getenv("AI_BASE_URL", "https://api.openai.com/v1"),
        api_key=api_key,
        model=os.getenv("AI_MODEL", "gpt-4o-mini"),
    )
    try:
        result = await run_review(client, request.diff_text, request.context)
        return result.model_dump(mode="json")
    except ReviewValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


class OrchestratedReviewRequest(BaseModel):
    diff_text: str = Field(min_length=1, max_length=200000)
    context: str | None = Field(default=None, max_length=200000)
    min_confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    agents: list[str] | None = Field(
        default=None,
        description="Optional subset: bug, security, performance, maintainability",
    )


@router.post("/orchestrate")
async def orchestrate_review(request: OrchestratedReviewRequest) -> dict:
    """Run selected specialist reviewers concurrently and aggregate validated findings."""
    import os

    from app.ai.agents.specialists import SPECIALISTS
    from app.ai.client import AIProviderError, OpenAICompatibleClient
    from app.ai.orchestrator import OrchestrationValidationError, run_multi_agent_review

    api_key = os.getenv("AI_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="AI provider is not configured. Set AI_API_KEY in the environment.",
        )

    available = {agent.name: agent for agent in SPECIALISTS}
    requested = request.agents or list(available)
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agents: {', '.join(unknown)}. Available agents: {', '.join(available)}",
        )
    selected = tuple(available[name] for name in available if name in requested)

    client = OpenAICompatibleClient(
        base_url=os.getenv("AI_BASE_URL", "https://api.openai.com/v1"),
        api_key=api_key,
        model=os.getenv("AI_MODEL", "gpt-4o-mini"),
    )
    try:
        return await run_multi_agent_review(
            client,
            request.diff_text,
            request.context,
            min_confidence=request.min_confidence,
            specialists=selected,
        )
    except OrchestrationValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/jobs/{job_id}")
async def get_review_job_status(job_id: str) -> dict:
    """Return the lifecycle status and result for an asynchronous review job."""
    from redis.exceptions import RedisError

    from app.jobs.store import get_job

    try:
        job = get_job(job_id)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Review status store is unavailable") from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Review job was not found or has expired")
    return job
