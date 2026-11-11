import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import DbSession, require_permission
from app.core.permissions import Permission
from app.models.enums import ScanStatus
from app.models.user import User
from app.schemas.domain import DomainCreate, DomainResponse
from app.schemas.error import ErrorResponse
from app.schemas.pagination import Page, Pagination
from app.services.domain_service import DomainService

router = APIRouter(
    prefix="/domains",
    tags=["domains"],
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid token"}},
)

NOT_FOUND = {404: {"model": ErrorResponse, "description": "Domain not found"}}
FORBIDDEN = {403: {"model": ErrorResponse, "description": "Role not allowed"}}


@router.get("", response_model=Page[DomainResponse], summary="List domains")
def list_domains(
    db: DbSession,
    pagination: Pagination,
    _: Annotated[User, Depends(require_permission(Permission.DOMAIN_READ))],
    status_filter: Annotated[
        ScanStatus | None, Query(alias="status", description="Filter by domain status")
    ] = None,
    search: Annotated[
        str | None, Query(max_length=253, description="Case-insensitive partial name match")
    ] = None,
) -> Page[DomainResponse]:
    items, total = DomainService(db).list(
        status=status_filter,
        search=search.strip() if search else None,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    return Page[DomainResponse](
        items=[DomainResponse.model_validate(item) for item in items],
        page=pagination.page,
        limit=pagination.limit,
        total=total,
    )


@router.post(
    "",
    response_model=DomainResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a domain for monitoring",
    responses={**FORBIDDEN, 409: {"model": ErrorResponse, "description": "Duplicate domain"}},
)
def create_domain(
    data: DomainCreate,
    db: DbSession,
    user: Annotated[User, Depends(require_permission(Permission.DOMAIN_CREATE))],
) -> DomainResponse:
    return DomainResponse.model_validate(DomainService(db).create(data.domain, user))


@router.get(
    "/{domain_id}",
    response_model=DomainResponse,
    summary="Get a domain",
    responses=NOT_FOUND,
)
def get_domain(
    domain_id: uuid.UUID,
    db: DbSession,
    _: Annotated[User, Depends(require_permission(Permission.DOMAIN_READ))],
) -> DomainResponse:
    return DomainResponse.model_validate(DomainService(db).get(domain_id))


@router.delete(
    "/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a domain with its scans and assets",
    responses={**FORBIDDEN, **NOT_FOUND},
)
def delete_domain(
    domain_id: uuid.UUID,
    db: DbSession,
    user: Annotated[User, Depends(require_permission(Permission.DOMAIN_DELETE))],
) -> Response:
    DomainService(db).delete(domain_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
