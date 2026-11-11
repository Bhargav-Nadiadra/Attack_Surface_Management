import re

FQDN_MAX_LENGTH = 253
LABEL_MAX_LENGTH = 63

_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_FORBIDDEN_FQDN_CHARS = frozenset("/:@*?#\\ \t\r\n")

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


def validate_fqdn(value: str) -> str:
    name = value.strip().lower()
    if not name:
        raise ValueError("Domain must not be empty.")
    if any(char in _FORBIDDEN_FQDN_CHARS for char in name):
        raise ValueError(
            "Domain must be a bare hostname such as 'example.com' "
            "(no scheme, path, port, credentials or wildcard)."
        )
    if name.endswith("."):
        name = name[:-1]

    if not name.isascii():
        try:
            name = name.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Domain contains invalid internationalized characters.") from exc

    if len(name) > FQDN_MAX_LENGTH:
        raise ValueError(f"Domain must be at most {FQDN_MAX_LENGTH} characters long.")

    labels = name.split(".")
    if len(labels) < 2:
        raise ValueError("Domain must contain at least two labels, e.g. 'example.com'.")
    for label in labels:
        _validate_label(label)
    if labels[-1].isdigit():
        raise ValueError("Domain must not be an IP address or end in a numeric TLD.")
    return name


def _validate_label(label: str) -> None:
    if not label:
        raise ValueError("Domain must not contain empty labels.")
    if len(label) > LABEL_MAX_LENGTH:
        raise ValueError(f"Each domain label must be at most {LABEL_MAX_LENGTH} characters.")
    if not _LABEL_PATTERN.match(label):
        raise ValueError(
            f"Invalid label '{label}': use letters, digits and hyphens, "
            "not starting or ending with a hyphen."
        )
