# server/app/api/v1/pricing/__init__.py

from fastapi import APIRouter

from . import fashion, laundry, garments, areas

router = APIRouter()

# router.include_router(fashion.router, prefix="/fashion", tags=["Pricing"])
# router.include_router(laundry.router, prefix="/laundry", tags=["Pricing"])
# router.include_router(garments.router, prefix="/garments", tags=["Pricing"])
# router.include_router(areas.router, prefix="/areas", tags=["Pricing"])
# 
router.include_router(fashion.router, tags=["Pricing"])
router.include_router(laundry.router, tags=["Pricing"])
router.include_router(garments.router, tags=["Pricing"])
router.include_router(areas.router, tags=["Pricing"])

