"""VOICE judge math + TestModel — no live API."""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from internal.config import settings
from tests.eval.voice_judge import (
    VoiceJudgeOut,
    judge_draft,
    set_voice_judge_model_override,
)


@pytest.fixture(autouse=True)
def _clear_voice_judge_override(monkeypatch: pytest.MonkeyPatch) -> None:
    set_voice_judge_model_override(None)
    # judge_draft now runs under recorder.track — keep unit tests off the DB.
    monkeypatch.setattr(settings, "llm_record_enabled", False)
    yield
    set_voice_judge_model_override(None)


def test_overall_is_mean_of_four_over_five() -> None:
    out = VoiceJudgeOut(scene=5, layers=3, bridge=4, locale=4, reason="ok")
    assert out.overall() == pytest.approx(16 / 20)
    payload = out.scores_payload()
    assert payload["overall"] == 0.8
    assert payload["scene"] == 5


@pytest.mark.asyncio
async def test_judge_draft_parses_testmodel() -> None:
    set_voice_judge_model_override(
        TestModel(
            call_tools=[],
            custom_output_args={
                "scene": 4,
                "layers": 4,
                "bridge": 3,
                "locale": 5,
                "reason": "HK OT hook, soft sell",
            },
        )
    )
    judged = await judge_draft(caption="星期五 OT 完飲罐嘢先走。")
    assert judged is not None
    assert judged.scores_payload()["overall"] == pytest.approx(16 / 20)
    assert judged.reason
