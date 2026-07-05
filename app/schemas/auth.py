
# """app/schemas/auth.py — Auth request/response schemas."""
# import re
# from typing import Optional
# from pydantic import BaseModel, EmailStr, Field, field_validator
# from app.enums.stitch import UserRole


# class SignupRequest(BaseModel):
#     name: str                   = Field(..., min_length=2, max_length=100)
#     email: EmailStr
#     phone: Optional[str]        = Field(None, max_length=30)
#     password: str               = Field(..., min_length=6, max_length=128)
#     referral_code: Optional[str] = Field(None, max_length=30)

#     @field_validator("name")
#     @classmethod
#     def name_no_html(cls, v: str) -> str:
#         if re.search(r"<[^>]+>", v):
#             raise ValueError("Name cannot contain HTML")
#         return v.strip()


# class SigninRequest(BaseModel):
#     email: EmailStr
#     password: str = Field(..., min_length=1)


# class VerifyOTPRequest(BaseModel):
#     email: EmailStr
#     otp: str = Field(..., min_length=4, max_length=10)
#     purpose: str = Field(default="verify")


# class ResendOTPRequest(BaseModel):
#     email: EmailStr
#     purpose: str = Field(default="verify")


# class ForgotPasswordRequest(BaseModel):
#     email: EmailStr


# class ResetPasswordRequest(BaseModel):
#     email: EmailStr
#     otp: str    = Field(..., min_length=4, max_length=10)
#     password: str = Field(..., min_length=6, max_length=128)
#     confirm: str  = Field(..., min_length=6, max_length=128)

#     @field_validator("confirm")
#     @classmethod
#     def passwords_match(cls, v, info) -> str:
#         if info.data.get("password") and v != info.data["password"]:
#             raise ValueError("Passwords do not match")
#         return v


# class ChangePasswordRequest(BaseModel):
#     current_password: str = Field(..., min_length=1)
#     new_password: str     = Field(..., min_length=6, max_length=128)
#     confirm: str          = Field(..., min_length=6)

#     @field_validator("confirm")
#     @classmethod
#     def passwords_match(cls, v, info) -> str:
#         if info.data.get("new_password") and v != info.data["new_password"]:
#             raise ValueError("Passwords do not match")
#         return v


# class RefreshRequest(BaseModel):
#     refresh_token: str


# class TokenResponse(BaseModel):
#     access_token: str
#     refresh_token: str
#     token_type: str = "bearer"
#     user: Optional[dict] = None


# class ImpersonateRequest(BaseModel):
#     target_user_id: int





# v2
# app/schemas/auth.py
from pydantic import BaseModel, EmailStr, Field
from typing import Optional


class SigninSchema(BaseModel):
    identifier: str = Field(..., min_length=1, description="Email, username, or phone")
    password: str = Field(..., min_length=1)


class SignupSchema(BaseModel):
    org_name: Optional[str] = Field(None, max_length=120)
    username: str = Field(..., min_length=2, max_length=50)
    email: EmailStr
    names: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=20)
    password: str = Field(..., min_length=4)
    org_name: Optional[str] = None   # used when creating a new org
    org_code: Optional[str] = None   # used when joining an existing org


class SignupVerifySchema(BaseModel):
    token: str
    email_code: str = Field(..., min_length=6, max_length=6)


class CreateStaffSchema(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    email: EmailStr
    names: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=20)
    password: Optional[str] = Field(None, min_length=4)
    role: Optional[str] = Field("staff", pattern="^(staff|cashier|manager)$")


class ChangePasswordSchema(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=4)


class ForgotPasswordSchema(BaseModel):
    email: EmailStr


class ResetPasswordSchema(BaseModel):
    token: str
    email_code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=4)

