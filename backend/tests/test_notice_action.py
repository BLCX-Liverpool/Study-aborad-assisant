from datetime import UTC, datetime

import pytest

from app.agents.notice.parser import NoticeActionParser
from app.schemas.action import ActionItem
from app.schemas.action import NoticeParseRequest


def test_notice_parser_extracts_assignment_deadline() -> None:
    response = NoticeActionParser().parse(
        NoticeParseRequest(
            user_id="user_1",
            text="COMP702 Assignment deadline: 10 October 2026 16:00. Submit on Moodle.",
            source_type="coursework_notice",
            source_id="file_1",
        )
    )

    item = response.action_items[0]
    assert item.action_type == "assignment_deadline"
    assert item.deadline is not None
    assert item.deadline.month == 10
    assert item.metadata["course_code"] == "COMP702"
    assert item.evidence[0].start_char is not None
    assert item.evidence[0].end_char is not None
    assert item.evidence[0].quote in "COMP702 Assignment deadline: 10 October 2026 16:00. Submit on Moodle."


def test_notice_parser_extracts_bill_due() -> None:
    response = NoticeActionParser().parse(
        NoticeParseRequest(
            user_id="user_1",
            text="Your council tax bill of £120 is due on 2026-11-05.",
            source_type="bill",
        )
    )

    assert response.action_items[0].action_type == "bill_due"
    assert response.action_items[0].metadata["amount"] == "£120"
    assert response.action_items[0].evidence[0].start_char is not None


@pytest.mark.asyncio
async def test_notice_parser_prefers_llm_structured_extraction() -> None:
    class FakeExtractor:
        async def extract(self, request):
            return [
                ActionItem(
                    title="LLM extracted appointment",
                    action_type="appointment",
                    source_type=request.source_type,
                    start_time=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
                    priority="medium",
                )
            ]

    response = await NoticeActionParser(llm_extractor=FakeExtractor()).parse_async(
        NoticeParseRequest(
            user_id="user_1",
            text="This message has no deterministic appointment keyword but should use LLM output.",
            source_type="notice",
        )
    )

    assert response.action_items[0].title == "LLM extracted appointment"
    assert any("LLM-first" in assumption for assumption in response.assumptions)


@pytest.mark.asyncio
async def test_notice_parser_falls_back_to_rules_when_llm_returns_no_items() -> None:
    class EmptyExtractor:
        async def extract(self, request):
            return []

    response = await NoticeActionParser(llm_extractor=EmptyExtractor()).parse_async(
        NoticeParseRequest(
            user_id="user_1",
            text="Your rent bill of £900 is due on 2026-10-10.",
            source_type="bill",
        )
    )

    assert response.action_items[0].action_type == "bill_due"
    assert any("fallback" in assumption.lower() for assumption in response.assumptions)
