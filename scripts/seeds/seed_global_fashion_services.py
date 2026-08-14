# scripts/seed_global_fashion_services.py
"""Seeds the platform-wide default fashion service catalog — rows with
organization_id = NULL, visible to every org, never duplicated per-tenant.
Run ONCE per environment (local, then production)."""
import sys
from pathlib import Path
# sys.path.insert(0, str(Path(__file__).resolve().parent))
project_root = Path(__file__).resolve().parents[2]  # seeds -> scripts -> server
sys.path.insert(0, str(project_root))
# 
from app.db.database import get_session_maker
from app.models.pricing import FashionService

DEFAULT_FASHION_SERVICES = [
    {"name": "Custom Tailoring", "icon": "fa-ruler-combined", "description": "Made-to-measure garments from scratch.", "display_order": 0},
    {"name": "Alteration", "icon": "fa-scissors", "description": "Resizing or adjusting an existing garment.", "display_order": 1},
    {"name": "Repair", "icon": "fa-thread", "description": "Mending tears, seams, or worn areas.", "display_order": 2},
    {"name": "Bespoke Design", "icon": "fa-pen-ruler", "description": "Fully custom design, from concept to finished piece.", "display_order": 3},
    {"name": "Material Pickup", "icon": "fa-truck", "description": "We collect fabric or materials from your location.", "display_order": 4},
    {"name": "Design Consultation", "icon": "fa-comments", "description": "One-on-one discussion to plan your piece.", "display_order": 5},
]

if __name__ == "__main__":
    db = get_session_maker()()
    try:
        existing = db.query(FashionService).filter(FashionService.organization_id.is_(None)).count()
        if existing > 0:
            print(f"{existing} global default(s) already exist — skipping to avoid duplicates.")
        else:
            for defn in DEFAULT_FASHION_SERVICES:
                db.add(FashionService(organization_id=None, is_active=True, **defn))
            db.commit()
            print(f"Seeded {len(DEFAULT_FASHION_SERVICES)} global fashion service defaults.")
    finally:
        db.close()

