from app.core.permissions import PermissionLevel, requires_approval
from app.schemas.email import EmailApprovalGateResult


class EmailApprovalGate:
    def evaluate_send(self) -> EmailApprovalGateResult:
        return EmailApprovalGateResult(
            action_name="send_email",
            permission_level=PermissionLevel.SEND.value,
            requires_approval=requires_approval(PermissionLevel.SEND),
            reason="Sending email is an external action and requires explicit user approval.",
        )

