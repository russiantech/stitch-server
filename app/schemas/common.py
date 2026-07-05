"""app/schemas/common.py — Shared Pydantic schema building blocks."""
from typing import Any, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class SuccessResponse(BaseModel):
    success: bool = True
    message: str


class DataResponse(SuccessResponse, Generic[T]):
    data: Optional[T] = None


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool


class PaginatedResponse(SuccessResponse, Generic[T]):
    data: List[T]
    meta: PaginationMeta


class IDResponse(SuccessResponse):
    id: int

