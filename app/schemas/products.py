from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class CategoryCreate(BaseModel):
    name: str           = Field(..., min_length=2, max_length=150)
    description: Optional[str] = None
    display_order: int  = 0


class CategoryUpdate(BaseModel):
    name: Optional[str]        = Field(None, min_length=2, max_length=150)
    description: Optional[str] = None
    display_order: Optional[int] = None


class CategoryOut(BaseModel):
    id: UUID
    name: str
    slug: str
    description: Optional[str]
    display_order: int
    products_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class ProductImageOut(BaseModel):
    id: UUID
    url: str
    media_type: str
    display_order: int
    alt_text: Optional[str]

    model_config = {"from_attributes": True}


class ProductCreate(BaseModel):
    name: str                   = Field(..., min_length=2, max_length=255)
    description: Optional[str]  = None
    price: Optional[Decimal]    = Field(None, ge=0)
    stock: int                  = Field(default=0, ge=0)
    sku: Optional[str]          = None
    category_ids: List[str]     = []
    image_action: str           = "add"   # add | replace


class ProductUpdate(BaseModel):
    name: Optional[str]         = Field(None, min_length=2, max_length=255)
    description: Optional[str]  = None
    price: Optional[Decimal]    = Field(None, ge=0)
    stock: Optional[int]        = Field(None, ge=0)
    sku: Optional[str]          = None
    category_ids: Optional[List[str]] = None
    is_active: Optional[bool]   = None
    image_action: str           = "add"


class ProductOut(BaseModel):
    id: UUID
    name: str
    slug: str
    description: Optional[str]
    price: Optional[Decimal]
    stock: int
    sku: Optional[str]
    is_active: bool
    categories: List[CategoryOut] = []
    images: List[ProductImageOut] = []
    image_urls: List[str] = []
    created_at: datetime

    model_config = {"from_attributes": True}

