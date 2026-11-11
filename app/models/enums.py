from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"


class ScanStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RecordType(StrEnum):
    A = "A"
    AAAA = "AAAA"
    NS = "NS"
    MX = "MX"
