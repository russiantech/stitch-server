"""
app/models/rbac.py — Role model.

Roles are org-scoped: each organization seeds its own set of roles
(admin, manager, staff, cashier, etc.) on first setup rather than
sharing a global role table across tenants. A super_admin role is
platform-level and has organization_id = None.

Uses TenantModel (not StitchBase) so organization_id is present as a
real indexed column — required for org-scoped queries and included in
get_summary() without having to declare it here manually.

The double-registration crash this file was causing:
  sqlalchemy.exc.InvalidRequestError: Table 'roles' is already defined …
came from `organization = relationship("Organization", backref="roles")`.
`backref` dynamically injects a `roles` attribute onto Organization at
import time. When rbac.py was imported through two different module
paths in the same process (auth_service → rbac, v1/__init__ → rbac),
SQLAlchemy ran __init_subclass__ twice on the same MetaData, seeing
the `roles` Table defined twice. Fixed by removing the backref entirely
and using an explicit back_populates on Organization instead if needed.
"""

from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import TenantModel
from app.models.association_tables import user_roles

if TYPE_CHECKING:
    from app.models.users import User


class Role(TenantModel, Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # M2M back-reference — no backref, explicit back_populates only.
    users: Mapped[List["User"]] = relationship(
        "User",
        secondary=user_roles,
        back_populates="roles",
        lazy="selectin",
    )

    def get_summary(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "is_default": self.is_default,
            "organization_id": str(self.organization_id) if self.organization_id else None,
        }

    def __repr__(self) -> str:
        return f"<Role name={self.name!r} org={self.organization_id}>"

