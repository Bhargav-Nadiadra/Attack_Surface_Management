import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings


def _settings(**overrides: object) -> Settings:
    values = settings.model_dump()
    values.update(overrides)
    return Settings.model_validate(values)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, []),
        ("", []),
        (" 1.1.1.1 , 8.8.8.8 ", ["1.1.1.1", "8.8.8.8"]),
        ("2606:4700:4700::1111", ["2606:4700:4700::1111"]),
    ],
)
def test_dns_nameservers_parsing(raw: str | None, expected: list[str]) -> None:
    assert _settings(DNS_NAMESERVERS=raw).dns_nameservers == expected


def test_dns_nameservers_reject_hostnames() -> None:
    with pytest.raises(ValidationError, match="not an IP address"):
        _settings(DNS_NAMESERVERS="1.1.1.1,dns.google")


def test_soft_time_limit_must_be_below_hard_limit() -> None:
    with pytest.raises(ValidationError, match="SCAN_SOFT_TIME_LIMIT_SECONDS"):
        _settings(SCAN_SOFT_TIME_LIMIT_SECONDS=120, SCAN_TIME_LIMIT_SECONDS=120)
