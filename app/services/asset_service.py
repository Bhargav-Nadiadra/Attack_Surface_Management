import uuid

from sqlalchemy.orm import Session

from app.models.enums import RecordType
from app.repositories.asset_repository import AssetRepository
from app.schemas.asset import AssetResponse


class AssetService:
    def __init__(self, session: Session) -> None:
        self.assets = AssetRepository(session)

    def list(
        self,
        *,
        domain_id: uuid.UUID | None,
        record_type: RecordType | None,
        latest_only: bool,
        offset: int,
        limit: int,
    ) -> tuple[list[AssetResponse], int]:
        rows, total = self.assets.list(
            domain_id=domain_id,
            record_type=record_type,
            latest_only=latest_only,
            offset=offset,
            limit=limit,
        )
        items = [
            AssetResponse(
                id=asset.id,
                domain=domain_name,
                domain_id=asset.domain_id,
                scan_id=asset.scan_id,
                type=asset.type,
                value=asset.value,
                created_at=asset.created_at,
            )
            for asset, domain_name in rows
        ]
        return items, total
