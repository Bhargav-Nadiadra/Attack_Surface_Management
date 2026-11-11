import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, Dispatcher, require_permission
from app.core.permissions import Permission
from app.models.user import User
from app.schemas.error import ErrorResponse
from app.schemas.pagination import Page, Pagination
from app.schemas.scan import ScanResponse, ScanTriggerResponse
from app.services.scan_service import ScanService

router = APIRouter(
    prefix="/domains/{domain_id}",
    tags=["scans"],
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid token"},
        404: {"model": ErrorResponse, "description": "Domain not found"},
    },
)


@router.post(
    "/scan",
    response_model=ScanTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a discovery scan",
    responses={
        403: {"model": ErrorResponse, "description": "Role not allowed"},
        409: {"model": ErrorResponse, "description": "A scan is already pending or running"},
    },
)
def trigger_scan(
    domain_id: uuid.UUID,
    db: DbSession,
    dispatcher: Dispatcher,
    user: Annotated[User, Depends(require_permission(Permission.SCAN_TRIGGER))],
) -> ScanTriggerResponse:
    scan = ScanService(db, dispatcher).trigger_scan(domain_id, user)
    return ScanTriggerResponse.model_validate(scan)


@router.get("/scans", response_model=Page[ScanResponse], summary="Scan history for a domain")
def list_scans(
    domain_id: uuid.UUID,
    db: DbSession,
    dispatcher: Dispatcher,
    pagination: Pagination,
    _: Annotated[User, Depends(require_permission(Permission.SCAN_READ))],
) -> Page[ScanResponse]:
    items, total = ScanService(db, dispatcher).list_for_domain(
        domain_id, offset=pagination.offset, limit=pagination.limit
    )
    return Page[ScanResponse](
        items=[ScanResponse.model_validate(item) for item in items],
        page=pagination.page,
        limit=pagination.limit,
        total=total,
    )
