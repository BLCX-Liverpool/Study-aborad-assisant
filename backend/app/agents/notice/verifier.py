from app.schemas.action import ActionItem


class NoticeActionVerifier:
    def verify(self, items: list[ActionItem]) -> tuple[list[ActionItem], list[str]]:
        verified: list[ActionItem] = []
        assumptions: list[str] = []
        for item in items:
            if item.action_type in {"assignment_deadline", "bill_due"} and item.deadline is None:
                item = item.model_copy(update={"priority": "medium"})
                assumptions.append(f"{item.action_type} has no verified deadline; priority downgraded.")
            if item.start_time and item.end_time and item.end_time < item.start_time:
                assumptions.append(f"Discarded invalid time range for {item.title}.")
                continue
            if item.evidence:
                item = item.model_copy(
                    update={
                        "evidence": [
                            evidence.model_copy(update={"confidence": max(evidence.confidence, 0.72)})
                            for evidence in item.evidence
                        ]
                    }
                )
            verified.append(item)
        return verified, assumptions
