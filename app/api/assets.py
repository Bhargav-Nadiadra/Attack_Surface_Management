import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_permission
from app.core.permissions import Permission
from app.models.enums import RecordType
from app.models.user import User
from app.schemas.asset import AssetResponse
from app.schemas.error import ErrorResponse
from app.schemas.pagination import Page, Pagination
from app.services.asset_service import AssetService

router = APIRouter(
    prefix="/assets",
    tags=["assets"],
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid token"}},
)


@router.get("", response_model=Page[AssetResponse], summary="List discovered assets")
def list_assets(
    db: DbSession,
    pagination: Pagination,
    _: Annotated[User, Depends(require_permission(Permission.ASSET_READ))],
    domain_id: Annotated[uuid.UUID | None, Query(description="Filter by domain id")] = None,
    record_type: Annotated[
        RecordType | None, Query(alias="type", description="Filter by DNS record type")
    ] = None,
    latest_only: Annotated[
        bool, Query(description="Only assets from each domain's latest completed scan")
    ] = False,
) -> Page[AssetResponse]:
    items, total = AssetService(db).list(
        domain_id=domain_id,
        record_type=record_type,
        latest_only=latest_only,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    return Page[AssetResponse](
        items=items, page=pagination.page, limit=pagination.limit, total=total
    )
