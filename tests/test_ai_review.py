import json

import httpx
import pytest

from app.ai.client import OpenAICompatibleClient
from app.ai.reviewer import run_review

DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,3 @@
 def divide(a, b):
+    return a / b
     return 0
"""


@pytest.mark.asyncio
async def test_review_accepts_only_findings_on_added_lines():
    review_json = {
        "overview": "Potential division by zero should be handled.",
        "risk_level": "medium",
        "findings": [
            {
                "file_path": "app.py",
                "line_number": 2,
                "severity": "medium",
                "category": "bug",
                "title": "Handle a zero divisor",
                "description": "The function can raise ZeroDivisionError when b is zero.",
                "recommendation": "Validate b before performing the division.",
                "evidence": "return a / b",
                "confidence": 0.95,
            },
            {
                "file_path": "app.py",
                "line_number": 1,
                "severity": "low",
                "category": "testing",
                "title": "Add tests for division",
                "description": "This location was not added by the change.",
                "recommendation": "Add a unit test.",
                "evidence": "def divide(a, b):",
                "confidence": 0.7,
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(review_json)}}]})

    client = OpenAICompatibleClient(
        "https://ai.example/v1", "test-key", "test-model", transport=httpx.MockTransport(handler)
    )
    result = await run_review(client, DIFF)

    assert result.reviewed_files == 1
    assert result.reviewed_added_lines == 1
    assert len(result.accepted_findings) == 1
    assert result.accepted_findings[0].line_number == 2
    assert result.rejected_findings == 1


@pytest.mark.asyncio
async def test_review_rejects_empty_diff_before_calling_provider():
    client = OpenAICompatibleClient(
        "https://ai.example/v1",
        "test-key",
        "test-model",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    from app.ai.reviewer import ReviewValidationError

    with pytest.raises(ReviewValidationError, match="cannot be empty"):
        await run_review(client, "   ")


@pytest.mark.asyncio
async def test_provider_invalid_json_is_safe_error():
    from app.ai.client import AIProviderError

    client = OpenAICompatibleClient(
        "https://ai.example/v1",
        "test-key",
        "test-model",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})
        ),
    )
    with pytest.raises(AIProviderError, match="invalid review response"):
        await client.complete_json("system", "user")
