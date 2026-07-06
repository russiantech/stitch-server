"""app/schemas/users.py — User and Address schemas."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field
from app.enums.stitch import UserRole, UserStatus


class AddressCreate(BaseModel):
    label: str       = Field(..., min_length=1, max_length=60)
    address_line: str = Field(..., min_length=3, max_length=500)
    area: Optional[str] = None
    city: str        = Field(default="Lagos", max_length=100)
    state: str       = Field(default="Lagos", max_length=100)
    is_default: bool = False


class AddressUpdate(BaseModel):
    label: Optional[str]        = Field(None, min_length=1, max_length=60)
    address_line: Optional[str] = Field(None, min_length=3)
    area: Optional[str]         = None
    city: Optional[str]         = None
    state: Optional[str]        = None
    is_default: Optional[bool]  = None


class AddressOut(BaseModel):
    id: UUID
    label: str
    address_line: str
    area: Optional[str]
    city: str
    state: str
    country: str
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserPublic(BaseModel):
    id: UUID
    names: str
    email: str
    username: Optional[str]
    phone: Optional[str]
    roles: List[UserRole]
    status: UserStatus
    is_verified: bool
    avatar_url: Optional[str]
    loyalty_points: int
    referral_code: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class UserProfile(UserPublic):
    addresses: List[AddressOut] = []


class UserUpdate(BaseModel):
    names: Optional[str]     = Field(None, min_length=2, max_length=100)
    username: Optional[str] = Field(None, min_length=3, max_length=60)
    phone: Optional[str]    = Field(None, max_length=30)
    bio: Optional[str]      = None
    avatar_url: Optional[str] = None


class UserAdminUpdate(UserUpdate):
    """Schema for admin-level user updates — fields staff/admins can edit
    but users themselves cannot (role, verification, deletion, etc.).
    All fields are optional so PATCH semantics work cleanly.
    """
    roles: Optional[List[UserRole]] = None
    status: Optional[UserStatus] = None
    is_verified: Optional[bool]  = None


class InviteUserRequest(BaseModel):
    names: str              = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone: Optional[str]    = None
    roles: List[UserRole]   = [UserRole.CUSTOMER]

