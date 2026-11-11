from typing import Any, Protocol

import dns.exception
import dns.name
import dns.resolver

from app.models.enums import RecordType


class DnsError(Exception):
    pass


class DomainNotFoundError(DnsError):
    pass


class DnsLookupError(DnsError):
    pass


class DnsResolver(Protocol):
    def resolve(self, domain: str, record_type: RecordType) -> list[str]: ...


class DnsPythonResolver:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self._resolver = dns.resolver.Resolver()
        self._resolver.timeout = min(timeout_seconds, 2.0)
        self._resolver.lifetime = timeout_seconds

    def resolve(self, domain: str, record_type: RecordType) -> list[str]:
        try:
            answer = self._resolver.resolve(
                domain, record_type.value, lifetime=self.timeout_seconds, search=False
            )
        except dns.resolver.NXDOMAIN as exc:
            raise DomainNotFoundError(f"Domain '{domain}' does not exist (NXDOMAIN).") from exc
        except dns.resolver.NoAnswer:
            return []
        except dns.exception.Timeout as exc:
            raise DnsLookupError(
                f"{record_type.value} lookup timed out after {self.timeout_seconds:g}s."
            ) from exc
        except dns.resolver.NoNameservers as exc:
            raise DnsLookupError(
                f"{record_type.value} lookup failed: no nameserver answered."
            ) from exc
        except dns.exception.DNSException as exc:
            raise DnsLookupError(f"{record_type.value} lookup failed: {exc}") from exc

        values = {self._normalize(record_type, rdata) for rdata in answer}
        values.discard("")
        return sorted(values)

    @staticmethod
    def _normalize(record_type: RecordType, rdata: Any) -> str:
        match record_type:
            case RecordType.A | RecordType.AAAA:
                return str(rdata.address)
            case RecordType.NS:
                return _host(rdata.target)
            case RecordType.MX:
                exchange = _host(rdata.exchange)
                return f"{rdata.preference} {exchange}" if exchange else ""


def _host(name: dns.name.Name) -> str:
    return name.to_text(omit_final_dot=True).lower() if name != dns.name.root else ""
