# scripts/setup_supabase.py

import sys
from pathlib import Path

from app.services.storage_service import ensure_bucket_exists
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_app_config

cfg = get_app_config()
print("Supabase URL:", repr(cfg.storage_config.supabase.url))
print("Service key present:", bool(cfg.storage_config.supabase.service_role_key))
print("Provider:", cfg.storage_config.provider)



if __name__ == "__main__":
    from app.services.storage_service import ensure_bucket_exists
    ensure_bucket_exists()
    print("Done.")