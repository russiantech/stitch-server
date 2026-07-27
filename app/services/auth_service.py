# app/services/auth_service.py
import logging
from typing import Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.users import User
from app.models.rbac import Role

logger = logging.getLogger(__name__)


def authenticate_user(db: Session, identifier: str, password: str):
    """Authenticate by email, username, or phone + password."""
    # identifier = identifier.strip().lower()
    
    user = db.query(User).filter(
        or_(
            User.email == identifier,
            User.username == identifier,
            User.phone == identifier,
        ),
        User.deleted == False,
    ).first()
    
    if not user:
        return None
    if not user.check_password(password):
        return None
    return user

# def create_user(
#     db: Session,
#     username: str,
#     email: str,
#     password: str = None,
#     names: str = None,
#     phone: str = None,
#     organization_id=None,
#     is_org_admin: bool = False,
#     role: str = "staff",
#     email_verified: bool = False,
#     password_hash: str = None,
# ) -> User:
#     user = User(
#         username=username.strip().lower(),
#         email=email.strip().lower(),
#         names=names,
#         phone=phone,
#         organization_id=organization_id,
#         is_org_admin=is_org_admin,
#         email_verified=email_verified,
#     )
#     if password_hash:
#         user.password_hash = password_hash
#     elif password:
#         user.set_password(password)
#     else:
#         raise ValueError("Either password or password_hash is required")

#     # Assign default role
#     default_role = db.query(Role).filter(Role.name == "staff").first()
#     if not default_role:
#         default_role = Role(name="staff", description="Default staff role", is_default=True)
#         db.add(default_role)
#         db.flush()

#     user.roles.append(default_role)
#     db.add(user)
#     db.commit()
#     db.refresh(user)
#     return user


def create_user(
    db: Session,
    username: str,
    email: str,
    password: str = None,
    names: str = None,
    phone: str = None,
    organization_id=None,
    is_org_admin: bool = False,
    role: Optional[str] = None,
    email_verified: bool = False,
    password_hash: str = None,
) -> User:
    user = User(
        username=username.strip().lower(),
        email=email.strip().lower(),
        names=names,
        phone=phone,
        organization_id=organization_id,
        is_org_admin=is_org_admin,
        email_verified=email_verified,
    )
    if password_hash:
        user.password_hash = password_hash
    elif password:
        user.set_password(password)
    else:
        raise ValueError("Either password or password_hash is required")

    # Determine the RBAC role: explicit `role` param wins if given;
    # otherwise derive sensibly from is_org_admin so callers that only
    # pass is_org_admin (as auth.py's signup flow does) still get the
    # correct role rather than silently defaulting to "staff".
    resolved_role_name = role or ("admin" if is_org_admin else "customer")

    resolved_role = db.query(Role).filter(Role.name == resolved_role_name).first()
    if not resolved_role:
        resolved_role = Role(name=resolved_role_name, description=f"{resolved_role_name.title()} role")
        db.add(resolved_role)
        db.flush()

    user.roles.append(resolved_role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def get_or_create_role(db: Session, name: str, description: str = None) -> Role:
    role = db.query(Role).filter(Role.name == name).first()
    if not role:
        role = Role(name=name, description=description or name)
        db.add(role)
        db.commit()
        db.refresh(role)
    return role
