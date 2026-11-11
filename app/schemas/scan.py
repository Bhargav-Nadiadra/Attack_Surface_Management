import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ScanStatus


class ScanTriggerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scan_id: uuid.UUID = Field(validation_alias="id")
    status: ScanStatus


class ScanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scan_id: uuid.UUID = Field(validation_alias="id")
    status: ScanStatus
    triggered_by: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
