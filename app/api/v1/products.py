"""app/api/v1/products.py — Fashion catalog: products and categories."""
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.api.deps.auth import get_current_user, require_admin
from app.core.config import get_app_config
from app.core.exceptions.custom_exceptions import NotFoundError
from app.db.database import get_db
from app.models.products import Product, ProductImage
from app.models.category import Category
from app.models.users import User
from app.schemas.products import (
    CategoryCreate, CategoryOut, CategoryUpdate,
    ProductOut, ProductImageOut,
)

from app.utils.helpers import make_slug
from app.utils.responses import api_response

router = APIRouter(tags=["Fashion Catalog"])


# ─── Categories ───────────────────────────────────────────────────────────────

@router.get("/categories")
def list_categories(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cats = db.query(Category).filter(Category.deleted == False).order_by(Category.display_order, Category.name).all()
    out  = []
    for c in cats:
        o = CategoryOut.model_validate(c)
        o.products_count = len([p for p in c.products if not p.deleted])
        out.append(o)
    return api_response(
        success=True,
        message="Categories fetched.",
        data=out,
    )


@router.post("/categories", status_code=201)
def create_category(p: CategoryCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    slug = make_slug(p.name, suffix=True)
    cat  = Category(name=p.name, slug=slug, description=p.description, display_order=p.display_order)
    db.add(cat); db.flush()
    return api_response(
        success=True,
        message="Category created.",
        data=CategoryOut.model_validate(cat),
        status_code=201,
    )


@router.put("/categories/{cat_id}")
def update_category(cat_id: str, p: CategoryUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    cat = db.get(Category, cat_id)
    if not cat or cat.deleted: raise NotFoundError("Category", cat_id)
    for k, v in p.model_dump(exclude_none=True).items(): setattr(cat, k, v)
    return api_response(
        success=True,
        message="Category updated.",
        data=CategoryOut.model_validate(cat),
    )


@router.delete("/categories/{cat_id}")
def delete_category(cat_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    cat = db.get(Category, cat_id)
    if not cat: raise NotFoundError("Category", cat_id)
    cat.soft_delete()
    return api_response(success=True, message="Category deleted.")


# ─── Products ─────────────────────────────────────────────────────────────────

@router.get("")
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    category_id: Optional[str] = None,
    search: Optional[str] = None,
    include_inactive: bool = False,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Product).options(joinedload(Product.categories), joinedload(Product.images))
    if not include_inactive:
        q = q.filter(Product.deleted == False, Product.is_active == True)
    else:
        q = q.filter(Product.deleted == False)
    if search:
        q = q.filter(Product.name.ilike(f"%{search}%"))
    if category_id:
        q = q.join(Product.categories).filter(Category.id == category_id)
    total = q.count()
    items = q.order_by(desc(Product.created_at)).offset((page-1)*page_size).limit(page_size).all()
    return api_response(
        success=True,
        message="Products fetched.",
        data={
            "items": [_product_out(p) for p in items],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.get("/{product_id}")
def get_product(product_id: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.query(Product).options(joinedload(Product.categories), joinedload(Product.images)).filter(
        Product.id == product_id, Product.deleted == False
    ).first()
    if not p: raise NotFoundError("Product", product_id)
    return api_response(
        success=True,
        message="Product fetched.",
        data=_product_out(p),
    )


@router.post("/", status_code=201)
async def create_product(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    price: Optional[str] = Form(None),
    stock: int = Form(0),
    category_ids: Optional[str] = Form(None),
    images: List[UploadFile] = File(default=[]),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    slug = make_slug(name, suffix=True)
    from decimal import Decimal
    product = Product(
        name=name, slug=slug, description=description,
        price=Decimal(price) if price else None, stock=stock,
    )
    db.add(product); db.flush()

    if category_ids:
        for cid in [c.strip() for c in category_ids.split(",") if c.strip()]:
            cat = db.get(Category, cid)
            if cat: product.categories.append(cat)

    # await _save_images(product.id, images, db)
    await SaveToSupabaseStorage(product.id, images, db)
    
    return api_response(
        success=True,
        message="Product created.",
        data=_product_out(product),
        status_code=201,
    )


@router.put("/{product_id}")
async def update_product(
    product_id: str,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    price: Optional[str] = Form(None),
    stock: Optional[int] = Form(None),
    category_ids: Optional[str] = Form(None),
    image_action: str = Form("add"),
    images: List[UploadFile] = File(default=[]),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    product = db.query(Product).options(joinedload(Product.categories), joinedload(Product.images)).filter(
        Product.id == product_id, Product.deleted == False
    ).first()
    if not product: raise NotFoundError("Product", product_id)

    from decimal import Decimal
    if name:        product.name = name
    if description is not None: product.description = description
    if price:       product.price = Decimal(price)
    if stock is not None: product.stock = stock

    if category_ids is not None:
        product.categories = []
        for cid in [c.strip() for c in category_ids.split(",") if c.strip()]:
            cat = db.get(Category, cid)
            if cat: product.categories.append(cat)

    if image_action == "replace":
        for img in product.images:
            img.soft_delete()

    if images:
        await SaveToSupabaseStorage(product.id, images, db)

    return api_response(
        success=True,
        message="Product updated.",
        data=_product_out(product),
    )


@router.delete("/{product_id}")
def delete_product(product_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if not p: raise NotFoundError("Product", product_id)
    p.soft_delete()
    return api_response(success=True, message="Product deleted.")


@router.delete("/{product_id}/images")
def delete_images(
    product_id: str,
    payload: dict,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    image_ids = payload.get("image_ids", [])
    for img_id in image_ids:
        img = db.get(ProductImage, img_id)
        if img and img.product_id == product_id:
            img.soft_delete()
    return api_response(success=True, message="Images removed.")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _product_out(p: Product) -> ProductOut:
    cats    = [CategoryOut.model_validate(c) for c in p.categories if not getattr(c, "deleted", False)]
    images  = [ProductImageOut.model_validate(i) for i in p.images if not getattr(i, "deleted", False)]
    urls    = [i.url for i in images]
    return ProductOut(
        id=p.id, name=p.name, slug=p.slug, description=p.description,
        price=p.price, stock=p.stock, sku=p.sku, is_active=p.is_active,
        categories=cats, images=images, image_urls=urls, created_at=p.created_at,
    )


# async def SaveToSupabaseStorage(product_id: str, files: List[UploadFile], db: Session):
#     existing_count = db.query(ProductImage).filter(ProductImage.product_id == product_id).count()

#     for i, file in enumerate(files):
#         if not file.filename: continue
#         ext      = Path(file.filename).suffix.lower()
#         fname    = f"{uuid.uuid4().hex}{ext}"
#         filepath = base_path / fname
#         contents = await file.read()
#         filepath.write_bytes(contents)
#         media_type = "video" if ext in (".mp4", ".webm", ".mov") else "image"
#         db.add(ProductImage(
#             product_id=product_id,
#             url=f"/static/products/{fname}",
#             media_type=media_type,
#             display_order=existing_count + i,
#         ))

# v2
from app.services.storage_service import upload_file

async def SaveToSupabaseStorage(product_id: str, files: List[UploadFile], db: Session):
    existing_count = db.query(ProductImage).filter(ProductImage.product_id == product_id).count()

    for i, file in enumerate(files):
        if not file.filename:
            continue
        contents = await file.read()
        url = upload_file(contents, file.filename, folder="products")
        ext = Path(file.filename).suffix.lower()
        media_type = "video" if ext in (".mp4", ".webm", ".mov") else "image"
        db.add(ProductImage(
            product_id=product_id,
            url=url,
            media_type=media_type,
            display_order=existing_count + i,
        ))
