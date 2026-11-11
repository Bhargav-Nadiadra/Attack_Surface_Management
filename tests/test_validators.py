import pytest

from app.schemas.validators import validate_fqdn, validate_password_strength


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("example.com", "example.com"),
        ("EXAMPLE.COM", "example.com"),
        ("  Sub.Example.com.  ", "sub.example.com"),
        ("a-b.co.uk", "a-b.co.uk"),
        ("xn--bcher-kva.de", "xn--bcher-kva.de"),
        ("bücher.de", "xn--bcher-kva.de"),
        ("123.example.com", "123.example.com"),
        (f"{'a' * 63}.com", f"{'a' * 63}.com"),
    ],
)
def test_valid_fqdns_are_normalized(raw: str, expected: str) -> None:
    assert validate_fqdn(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "localhost",
        "https://example.com",
        "example.com/path",
        "example.com:443",
        "user@example.com",
        "*.example.com",
        "exa mple.com",
        "example..com",
        ".example.com",
        "-bad-.com",
        "bad-.com",
        "ex_ample.com",
        "192.168.1.1",
        "::1",
        "example.123",
        f"{'a' * 64}.com",
        ".".join(["a" * 63] * 4) + ".com",
    ],
)
def test_invalid_fqdns_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        validate_fqdn(raw)


def test_valid_password_passes() -> None:
    assert validate_password_strength("Str0ng!Pass") == "Str0ng!Pass"


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("Sh0rt!", "at least 8 characters"),
        ("alllower1!", "uppercase"),
        ("ALLUPPER1!", "lowercase"),
        ("NoDigits!!", "digit"),
        ("NoSpecial12", "special"),
        ("Has Space1!", "whitespace"),
        ("Aa1!" + "x" * 70, "at most 72 bytes"),
    ],
)
def test_weak_passwords_are_rejected(password: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_password_strength(password)
