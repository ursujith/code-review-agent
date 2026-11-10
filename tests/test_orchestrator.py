import asyncio

import pytest

from app.ai.agents.specialists import SPECIALISTS
from app.ai.orchestrator import run_multi_agent_review


DIFF = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,2 +1,3 @@
+password = 'hard-coded-secret'
 def run():
     return True
"""


class FakeClient:
    model = "fake-model"

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def complete_json(self, system_prompt, user_prompt):
        self.calls.append(system_prompt)
        await asyncio.sleep(0)
        for name in ("bug", "security", "performance", "maintainability"):
            if f"specialist: {name}" in system_prompt.lower():
                return self.responses.get(name, {"findings": []})
        return {"findings": []}


def finding(**overrides):
    result = {
        "file_path": "app.py",
        "line_number": 1,
        "severity": "high",
        "category": "other",
        "title": "Hard-coded credential",
        "description": "A credential is embedded directly in source code.",
        "recommendation": "Load the value from a secret manager.",
        "evidence": "password = 'hard-coded-secret'",
        "confidence": 0.94,
    }
    result.update(overrides)
    return result


@pytest.mark.asyncio
async def test_multi_agent_review_aggregates_and_scopes_categories():
    client = FakeClient({
        "security": {"findings": [finding()]},
        "bug": {"findings": [finding(category="bug", severity="medium", title="Incorrect fallback value")]},
    })
    selected = tuple(agent for agent in SPECIALISTS if agent.name in {"bug", "security"})
    result = await run_multi_agent_review(client, DIFF, specialists=selected)

    assert len(client.calls) == 2
    assert result["metrics"]["reviewed_files"] == 1
    assert result["metrics"]["accepted_findings"] == 2
    assert {item["category"] for item in result["findings"]} == {"bug", "security"}
    assert result["risk_level"] == "high"
    assert result["partial"] is False


@pytest.mark.asyncio
async def test_multi_agent_review_rejects_old_line_and_low_confidence():
    client = FakeClient({
        "security": {"findings": [
            finding(line_number=2, title="Old line issue"),
            finding(line_number=1, title="Weak evidence", confidence=0.2),
        ]}
    })
    security = next(agent for agent in SPECIALISTS if agent.name == "security")
    result = await run_multi_agent_review(client, DIFF, specialists=(security,))

    assert result["findings"] == []
    assert result["metrics"]["rejected_invalid_locations"] == 1
    assert result["metrics"]["rejected_low_confidence"] == 1
    assert result["risk_level"] == "none"


@pytest.mark.asyncio
async def test_multi_agent_review_reports_partial_failure():
    class PartialClient(FakeClient):
        async def complete_json(self, system_prompt, user_prompt):
            if "specialist: security" in system_prompt.lower():
                raise RuntimeError("simulated failure")
            return {"findings": []}

    # The orchestrator preserves successful specialists even if another raises.
    client = PartialClient({})
    selected = tuple(agent for agent in SPECIALISTS if agent.name in {"bug", "security"})
    result = await run_multi_agent_review(client, DIFF, specialists=selected)
    assert result["partial"] is True
    assert result["agents"]["successful"] == ["bug"]
    assert result["agents"]["failed"][0]["name"] == "security"
