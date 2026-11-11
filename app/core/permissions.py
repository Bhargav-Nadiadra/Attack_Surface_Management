from enum import StrEnum

from app.models.enums import UserRole


class Permission(StrEnum):
    USER_REGISTER = "user:register"
    DOMAIN_READ = "domain:read"
    DOMAIN_CREATE = "domain:create"
    DOMAIN_DELETE = "domain:delete"
    SCAN_TRIGGER = "scan:trigger"
    SCAN_READ = "scan:read"
    ASSET_READ = "asset:read"


_ALL_ROLES = frozenset(UserRole)

ROLE_PERMISSIONS: dict[Permission, frozenset[UserRole]] = {
    Permission.USER_REGISTER: frozenset({UserRole.ADMIN}),
    Permission.DOMAIN_READ: _ALL_ROLES,
    Permission.DOMAIN_CREATE: frozenset({UserRole.ADMIN, UserRole.ANALYST}),
    Permission.DOMAIN_DELETE: frozenset({UserRole.ADMIN}),
    Permission.SCAN_TRIGGER: frozenset({UserRole.ADMIN, UserRole.ANALYST}),
    Permission.SCAN_READ: _ALL_ROLES,
    Permission.ASSET_READ: _ALL_ROLES,
}


def roles_for(permission: Permission) -> frozenset[UserRole]:
    return ROLE_PERMISSIONS[permission]


def has_permission(role: UserRole, permission: Permission) -> bool:
    return role in ROLE_PERMISSIONS[permission]
