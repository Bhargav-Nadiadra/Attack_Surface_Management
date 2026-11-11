import re

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_BYTES = 72

_PASSWORD_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[A-Z]"), "one uppercase letter"),
    (re.compile(r"[a-z]"), "one lowercase letter"),
    (re.compile(r"\d"), "one digit"),
    (re.compile(r"[^A-Za-z0-9]"), "one special character"),
)


def validate_password_strength(password: str) -> str:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long.")
    if len(password.encode()) > PASSWORD_MAX_BYTES:
        raise ValueError(f"Password must be at most {PASSWORD_MAX_BYTES} bytes long.")
    if any(char.isspace() for char in password):
        raise ValueError("Password must not contain whitespace.")
    missing = [label for pattern, label in _PASSWORD_RULES if not pattern.search(password)]
    if missing:
        raise ValueError(f"Password must contain at least {', '.join(missing)}.")
    return password
