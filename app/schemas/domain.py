import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ScanStatus
from app.schemas.validators import validate_fqdn


class DomainCreate(BaseModel):
    domain: str = Field(examples=["example.com"], max_length=255)

    @field_validator("domain")
    @classmethod
    def check_domain(cls, value: str) -> str:
        return validate_fqdn(value)


class DomainResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: ScanStatus
    created_at: datetime
    updated_at: datetime
