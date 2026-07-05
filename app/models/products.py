"""app/models/products.py — Product, Category, ProductImage (fashion catalogue)."""
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from app.models.association_tables import ProductCategory
from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import StitchBase

class Product(StitchBase, Base):
    __tablename__ = "products"

    name: Mapped[str]               = mapped_column(String(255), nullable=False)
    slug: Mapped[str]               = mapped_column(String(300), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    stock: Mapped[int]              = mapped_column(Integer, default=0)
    sku: Mapped[Optional[str]]      = mapped_column(String(100), unique=True)
    is_active: Mapped[bool]         = mapped_column(Boolean, default=True)

    categories: Mapped[List["Category"]] = relationship("Category", secondary=ProductCategory, back_populates="products")
    images: Mapped[List["ProductImage"]] = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.display_order")

    @property
    def image_urls(self) -> List[str]:
        return [img.url for img in self.images if not img.deleted]


class ProductImage(StitchBase, Base):
    __tablename__ = "product_images"

    product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str]           = mapped_column(Text, nullable=False)
    media_type: Mapped[str]    = mapped_column(String(20), default="image")  # image | video
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    alt_text: Mapped[Optional[str]] = mapped_column(String(255))

    product: Mapped["Product"] = relationship("Product", back_populates="images")


