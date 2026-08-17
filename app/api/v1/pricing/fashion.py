# app/api/v1/pricing.py
"""app/api/v1/pricing.py — Garment types, laundry services, delivery areas."""
from fastapi import APIRouter, Depends
from app.api.deps.rbac import require_roles
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.api.deps.auth import get_current_user
from app.core.exceptions.custom_exceptions import NotFoundError
from app.db.database import get_db
from app.models.pricing import FashionService, FashionServiceOverride, FashionFeeSettings
from app.models.users import User
from app.schemas.pricing import (
    FashionServiceCreate, FashionServiceOut, FashionServiceUpdate,
)
from app.utils.responses import api_response

router = APIRouter(tags=["Pricing"])

# ─── Fashion Fee Settings ─────────────────────────────────────────────────────
from app.models.pricing import FashionFeeSettings
from app.schemas.pricing import FashionFeeSettingsOut, FashionFeeSettingsUpdate

def _get_or_create_fashion_fees(db: Session, organization_id: str) -> FashionFeeSettings:
    fees = db.query(FashionFeeSettings).filter(
        FashionFeeSettings.organization_id == organization_id
    ).first()
    if not fees:
        fees = FashionFeeSettings(organization_id=organization_id)
        db.add(fees)
        db.flush()
    return fees


def _effective_fashion_services(db: Session, organization_id: str, include_inactive: bool = False):
    """Global defaults (minus any this org has hidden) + this org's own
    fashion services. Stamps `is_global` on every returned row in the same
    pass — same pattern as garments/laundry/areas. In admin/management
    context (include_inactive=True), hidden defaults are kept in the list
    instead of dropped, so they can still be restored, and are represented
    as is_active=False on the returned object (display-only — the
    underlying row's real is_active is untouched, no commit here)."""
    hidden_ids = {
        row.fashion_service_id for row in db.query(FashionServiceOverride.fashion_service_id).filter(
            FashionServiceOverride.organization_id == organization_id
        ).all()
    }
    q = db.query(FashionService).filter(
        FashionService.deleted == False,
        or_(FashionService.organization_id.is_(None), FashionService.organization_id == organization_id),
    )
    if not include_inactive:
        q = q.filter(FashionService.is_active.isnot(False))
    services = q.order_by(FashionService.display_order, FashionService.name).all()

    visible = []
    for s in services:
        is_hidden_default = s.organization_id is None and s.id in hidden_ids
        if is_hidden_default and not include_inactive:
            continue
        if is_hidden_default:
            s.is_active = False  # display-only override, not persisted
        s.is_global = s.organization_id is None
        visible.append(s)
    return visible


@router.get("/fashion-fees")
def get_fashion_fees(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fees = _get_or_create_fashion_fees(db, user.organization_id)
    return api_response(True, "Fashion fees fetched.", data=FashionFeeSettingsOut.model_validate(fees))


@router.put("/fashion-fees", dependencies=[Depends(require_roles("admin", "super_admin"))])
def update_fashion_fees(
    payload: FashionFeeSettingsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fees = _get_or_create_fashion_fees(db, user.organization_id)
    data = payload.model_dump(exclude_unset=True)   # exclude_unset, NOT exclude_none —
    # a deliberately-sent empty list [] or a real applies_to list must NOT be dropped,
    # which exclude_none would risk if any edge case sends None meaningfully.
    for k, v in data.items():
        setattr(fees, k, v)
    db.commit()
    db.refresh(fees)
    return api_response(True, "Fashion fees updated.", data=FashionFeeSettingsOut.model_validate(fees))


@router.get("/fashion-services")
def list_fashion_services(
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services = _effective_fashion_services(db, user.organization_id, include_inactive)
    return api_response(True, "Fashion services fetched.", data=[FashionServiceOut.model_validate(s) for s in services])


@router.post("/fashion-services/{service_id}/hide", dependencies=[Depends(require_roles("admin", "super_admin"))])
def hide_default_fashion_service(
    service_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc = db.query(FashionService).filter(FashionService.id == service_id, FashionService.organization_id.is_(None)).first()
    if not svc:
        raise NotFoundError("Global fashion service", service_id)
    exists = db.query(FashionServiceOverride).filter(
        FashionServiceOverride.organization_id == user.organization_id,
        FashionServiceOverride.fashion_service_id == service_id,
    ).first()
    if not exists:
        db.add(FashionServiceOverride(organization_id=user.organization_id, fashion_service_id=service_id))
        db.commit()
    return api_response(True, "Default service hidden for your organization.")


@router.post("/fashion-services/{service_id}/unhide", dependencies=[Depends(require_roles("admin", "super_admin"))])
def unhide_default_fashion_service(
    service_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(FashionServiceOverride).filter(
        FashionServiceOverride.organization_id == user.organization_id,
        FashionServiceOverride.fashion_service_id == service_id,
    ).delete()
    db.commit()
    return api_response(True, "Default service restored.")


@router.post("/fashion-services", status_code=201, dependencies=[Depends(require_roles("admin", "super_admin"))])
def create_fashion_service(
    payload: FashionServiceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Always created scoped to the admin's own org — never global.
    # Global defaults are only ever seeded via the one-off script, never
    # created through this tenant-facing endpoint.
    svc = FashionService(organization_id=user.organization_id, **payload.model_dump())
    db.add(svc); db.flush()
    return api_response(True, "Fashion service created.", data=FashionServiceOut.model_validate(svc), status_code=201)


@router.put("/fashion-services/{service_id}", dependencies=[Depends(require_roles("admin", "super_admin"))])
def update_fashion_service(
    service_id: str,
    payload: FashionServiceUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Deliberately scoped to organization_id == user's own org — an admin
    # can never edit a global default (organization_id IS NULL) through
    # this endpoint, since that would silently change it for every tenant
    # on the platform. If they want a different version of a default
    # service, they create their own org-specific entry with the same
    # or a different name instead.
    svc = db.query(FashionService).filter(
        FashionService.id == service_id, FashionService.organization_id == user.organization_id
    ).first()
    if not svc:
        raise NotFoundError("Fashion service", service_id)
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(svc, k, v)
    db.commit(); db.refresh(svc)
    return api_response(True, "Fashion service updated.", data=FashionServiceOut.model_validate(svc))


@router.delete("/fashion-services/{service_id}", dependencies=[Depends(require_roles("admin", "super_admin"))])
def delete_fashion_service(
    service_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc = db.query(FashionService).filter(
        FashionService.id == service_id, FashionService.organization_id == user.organization_id
    ).first()
    if not svc:
        raise NotFoundError("Fashion service", service_id)
    svc.deleted = True   # StitchBase's soft-delete column — clean assignment, no ternary
    db.commit()
    return api_response(True, "Fashion service removed.")

