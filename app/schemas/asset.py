import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import RecordType


class AssetResponse(BaseModel):
    id: uuid.UUID
    domain: str
    domain_id: uuid.UUID
    scan_id: uuid.UUID
    type: RecordType
    value: str
    created_at: datetime
