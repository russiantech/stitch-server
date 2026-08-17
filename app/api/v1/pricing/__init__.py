# server/app/api/v1/pricing/__init__.py

from fastapi import APIRouter

from . import fashion, laundry, garments, areas

router = APIRouter()

router.include_router(fashion.router, tags=["Pricing"])
router.include_router(laundry.router, tags=["Pricing"])
router.include_router(garments.router, tags=["Pricing"])
router.include_router(areas.router, tags=["Pricing"])

