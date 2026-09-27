import re
from datetime import UTC, datetime

from app.agents.notice.llm_extractor import LlmNoticeExtractor
from app.agents.notice.verifier import NoticeActionVerifier
from app.schemas.action import ActionItem, NoticeParseRequest, NoticeParseResponse
from app.schemas.common import EvidenceRef


class NoticeActionParser:
    def __init__(
        self,
        llm_extractor: LlmNoticeExtractor | None = None,
        verifier: NoticeActionVerifier | None = None,
    ) -> None:
        self.llm_extractor = llm_extractor
        self.verifier = verifier or NoticeActionVerifier()

    def parse(self, request: NoticeParseRequest) -> NoticeParseResponse:
        return self._parse_rules(request)

    async def parse_async(self, request: NoticeParseRequest) -> NoticeParseResponse:
        if self.llm_extractor is not None:
            llm_items = await self.llm_extractor.extract(request)
            if llm_items:
                action_items, verifier_assumptions = self.verifier.verify(
                    _deduplicate(llm_items)
                )
                return NoticeParseResponse(
                    action_items=action_items,
                    missing_information=_missing_information_for_items(action_items),
                    assumptions=[
                        "Parsed with LLM-first structured extraction; deterministic rules were kept as fallback.",
                        *verifier_assumptions,
                    ],
                )
        response = self._parse_rules(request)
        return response.model_copy(
            update={
                "assumptions": [
                    *response.assumptions,
                    "LLM structured extraction returned no valid items or was unavailable; deterministic fallback was used.",
                ]
            }
        )

    def _parse_rules(self, request: NoticeParseRequest) -> NoticeParseResponse:
        text = request.text.strip()
        missing_information: list[str] = []
        assumptions: list[str] = ["Parsed with deterministic notice rules; no external tools were called."]
        action_items: list[ActionItem] = []

        deadline = _extract_datetime(text)
        lowered = text.lower()

        if _contains_any(lowered, ("assignment", "coursework", "作业", "论文", "submission", "submit")):
            evidence = _evidence_for_signals(request, text, ("assignment", "coursework", "作业", "论文", "submission", "submit"))
            if deadline is None:
                missing_information.append("assignment_deadline.deadline")
            action_items.append(
                ActionItem(
                    title=_title("Assignment deadline", text),
                    action_type="assignment_deadline",
                    source_type=request.source_type,
                    source_id=request.source_id,
                    description=text,
                    deadline=deadline,
                    priority="high",
                    evidence=evidence,
                    metadata={"course_code": _extract_course_code(text)},
                )
            )

        if _contains_any(lowered, ("bill", "invoice", "payment", "due", "账单", "付款", "缴费")):
            evidence = _evidence_for_signals(request, text, ("bill", "invoice", "payment", "due", "账单", "付款", "缴费"))
            if deadline is None:
                missing_information.append("bill_due.deadline")
            action_items.append(
                ActionItem(
                    title=_title("Bill due", text),
                    action_type="bill_due",
                    source_type=request.source_type,
                    source_id=request.source_id,
                    description=text,
                    deadline=deadline,
                    priority="high",
                    evidence=evidence,
                    metadata={"amount": _extract_amount(text)},
                )
            )

        if _contains_any(lowered, ("tenancy", "landlord", "rent", "deposit", "租房", "房东", "押金")):
            evidence = _evidence_for_signals(request, text, ("tenancy", "landlord", "rent", "deposit", "租房", "房东", "押金"))
            action_items.append(
                ActionItem(
                    title=_title("Tenancy action", text),
                    action_type="tenancy_action",
                    source_type=request.source_type,
                    source_id=request.source_id,
                    description=text,
                    deadline=deadline,
                    priority="medium" if deadline is None else "high",
                    evidence=evidence,
                    metadata={"amount": _extract_amount(text)},
                )
            )

        if _contains_any(lowered, ("flight", "airport", "departure", "arrival", "航班", "机场", "出发", "到达")):
            evidence = _evidence_for_signals(request, text, ("flight", "airport", "departure", "arrival", "航班", "机场", "出发", "到达"))
            if deadline is None:
                missing_information.append("travel_event.start_time")
            action_items.append(
                ActionItem(
                    title=_title("Travel event", text),
                    action_type="travel_event",
                    source_type=request.source_type,
                    source_id=request.source_id,
                    description=text,
                    start_time=deadline,
                    location=_extract_location(text),
                    priority="medium",
                    evidence=evidence,
                )
            )

        if _contains_any(lowered, ("appointment", "meeting", "interview", "预约", "会议", "面试")):
            evidence = _evidence_for_signals(request, text, ("appointment", "meeting", "interview", "预约", "会议", "面试"))
            if deadline is None:
                missing_information.append("appointment.start_time")
            action_items.append(
                ActionItem(
                    title=_title("Appointment", text),
                    action_type="appointment",
                    source_type=request.source_type,
                    source_id=request.source_id,
                    description=text,
                    start_time=deadline,
                    location=_extract_location(text),
                    priority="medium",
                    evidence=evidence,
                )
            )

        if _contains_any(lowered, ("reply", "respond", "email", "回复", "邮件", "回信")):
            evidence = _evidence_for_signals(request, text, ("reply", "respond", "email", "回复", "邮件", "回信"))
            action_items.append(
                ActionItem(
                    title=_title("Email follow-up", text),
                    action_type="email_follow_up",
                    source_type=request.source_type,
                    source_id=request.source_id,
                    description=text,
                    deadline=deadline,
                    priority="medium" if deadline is None else "high",
                    evidence=evidence,
                )
            )

        if not action_items:
            evidence = _evidence(request, text)
            action_items.append(
                ActionItem(
                    title=_title("Review notice", text),
                    action_type="generic_task",
                    source_type=request.source_type,
                    source_id=request.source_id,
                    description=text,
                    deadline=deadline,
                    priority="medium",
                    evidence=evidence,
                )
            )
            assumptions.append("No domain-specific action pattern matched; created a review task.")

        verified, verifier_assumptions = self.verifier.verify(_deduplicate(action_items))
        return NoticeParseResponse(
            action_items=verified,
            missing_information=sorted(set(missing_information)),
            assumptions=[*assumptions, *verifier_assumptions],
        )


MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _extract_datetime(text: str) -> datetime | None:
    iso = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?\b", text)
    if iso:
        year, month, day, hour, minute = iso.groups()
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 9),
            int(minute or 0),
            tzinfo=UTC,
        )

    month_match = re.search(
        r"\b(\d{1,2})\s+([A-Za-z]+)(?:\s+(20\d{2}))?(?:\s+(?:at\s+)?(\d{1,2}):(\d{2}))?\b",
        text,
        flags=re.IGNORECASE,
    )
    if month_match:
        day, month_text, year, hour, minute = month_match.groups()
        month = MONTHS.get(month_text.lower())
        if month:
            return datetime(
                int(year or datetime.now(UTC).year),
                month,
                int(day),
                int(hour or 9),
                int(minute or 0),
                tzinfo=UTC,
            )

    return None


def _contains_any(text: str, signals: tuple[str, ...]) -> bool:
    return any(signal.lower() in text for signal in signals)


def _title(prefix: str, text: str) -> str:
    compact = " ".join(text.split())
    return f"{prefix}: {compact[:72]}"


def _extract_course_code(text: str) -> str | None:
    match = re.search(r"\b[A-Z]{2,}\d{2,}[A-Z]?\b", text)
    return match.group(0) if match else None


def _extract_amount(text: str) -> str | None:
    match = re.search(r"(?:£|\$|€)\s?\d+(?:,\d{3})*(?:\.\d{2})?", text)
    return match.group(0) if match else None


def _extract_location(text: str) -> str | None:
    match = re.search(r"(?:at|in|from|to)\s+([A-Z][A-Za-z\s]{2,40})", text)
    return match.group(1).strip() if match else None


def _evidence(request: NoticeParseRequest, text: str) -> list[EvidenceRef]:
    return [
        EvidenceRef(
            source_file_id=request.source_id,
            source_name=request.source_name,
            quote=text[:500],
            start_char=0,
            end_char=min(len(text), 500),
            confidence=0.75,
        )
    ]


def _evidence_for_signals(
    request: NoticeParseRequest,
    text: str,
    signals: tuple[str, ...],
) -> list[EvidenceRef]:
    lowered = text.lower()
    best_start = 0
    for signal in signals:
        index = lowered.find(signal.lower())
        if index >= 0:
            best_start = index
            break
    sentence_start = max(text.rfind(".", 0, best_start), text.rfind("\n", 0, best_start), text.rfind("。", 0, best_start)) + 1
    sentence_end_candidates = [pos for pos in (text.find(".", best_start), text.find("\n", best_start), text.find("。", best_start)) if pos >= 0]
    sentence_end = min(sentence_end_candidates) + 1 if sentence_end_candidates else min(len(text), best_start + 500)
    quote = text[sentence_start:sentence_end].strip() or text[:500]
    return [
        EvidenceRef(
            source_file_id=request.source_id,
            source_name=request.source_name,
            quote=quote,
            start_char=sentence_start,
            end_char=sentence_end,
            confidence=0.82,
        )
    ]


def _deduplicate(items: list[ActionItem]) -> list[ActionItem]:
    seen: set[tuple[str, str | None, datetime | None, datetime | None]] = set()
    deduped: list[ActionItem] = []
    for item in items:
        key = (item.action_type, item.source_id, item.deadline, item.start_time)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _missing_information_for_items(items: list[ActionItem]) -> list[str]:
    missing: list[str] = []
    for item in items:
        if item.action_type in {"assignment_deadline", "bill_due"} and item.deadline is None:
            missing.append(f"{item.action_type}.deadline")
        if item.action_type in {"travel_event", "appointment"} and item.start_time is None:
            missing.append(f"{item.action_type}.start_time")
    return sorted(set(missing))
