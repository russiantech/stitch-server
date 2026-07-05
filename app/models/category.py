# app/models/category.py
"""app/models/category.py — Fashion catalog category (global, not tenant-scoped).

Kept intentionally simple to match Product (also StitchBase-only, global
across the platform) and the CategoryOut/CategoryCreate/CategoryUpdate
schemas used by api/v1/products.py.
"""
from typing import List, Optional

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import StitchBase
from app.models.association_tables import ProductCategory


class Category(StitchBase, Base):
    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    products: Mapped[List["Product"]] = relationship(
        "Product", secondary=ProductCategory, back_populates="categories"
    )

    def __repr__(self) -> str:
        return f"<Category id={self.id} name={self.name!r}>"
