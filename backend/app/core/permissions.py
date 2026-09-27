from enum import StrEnum


class PermissionLevel(StrEnum):
    READ = "READ"
    SEARCH = "SEARCH"
    WRITE_DRAFT = "WRITE_DRAFT"
    WRITE_LOCAL = "WRITE_LOCAL"
    SEND = "SEND"
    DELETE = "DELETE"
    PAY = "PAY"


APPROVAL_REQUIRED_LEVELS = {
    PermissionLevel.SEND,
    PermissionLevel.DELETE,
    PermissionLevel.PAY,
}


def requires_approval(level: PermissionLevel) -> bool:
    return level in APPROVAL_REQUIRED_LEVELS

