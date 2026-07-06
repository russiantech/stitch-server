# main.py
"""
Stitch Platform — FastAPI application entry point.
Run: uvicorn main:app --reload --port 8000
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.core.config import get_app_config
from app.core.exceptions.handlers import setup_exception_handlers
from app.api.root_router import root_router
from app.api.v1.v1_router import v1_router
from app.db.database import close_db, create_tables
# from app.services.storage_service import ensure_bucket_exists

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_app_config()
    logger.info("=" * 60)
    logger.info("  %s Platform starting up", cfg.general_config.site_name)
    logger.info("  Environment : %s", "development" if cfg.general_config.development_mode else "production")
    logger.info("  API prefix  : %s", cfg.general_config.api_prefix)
    logger.info("  Docs        : %s", "/docs" if cfg.general_config.development_mode else "disabled")
    logger.info("=" * 60)

    try:
        create_tables()
        logger.info("Database tables verified.")
    except Exception as exc:
        logger.error("Database startup error: %s", exc)
        if not cfg.general_config.development_mode:
            raise

    """ 
        My recommendation: use the one-off script approach for actual bucket creation (run once per environment when you provision), and skip calling ensure_bucket_exists() from the request-serving lifespan — keeps cold starts fast and avoids repeatedly hitting Supabase's API on every deploy/invocation for something that only needs to happen once.
    """
    # try:
    #     ensure_bucket_exists()
    # except Exception as exc:
    #     logger.error("Supabase storage bucket check failed: %s", exc)
    #     if not cfg.general_config.development_mode:
    #         raise
        
    yield

    logger.info("Stitch shutting down...")
    close_db()


# ─── App factory ──────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    cfg = get_app_config()
    is_dev = cfg.general_config.development_mode

    app = FastAPI(
        title=f"{cfg.general_config.site_name} API",
        description=cfg.general_config.site_description,
        version=cfg.general_config.api_version,
        docs_url="/docs"    if is_dev else None,
        redoc_url="/redoc"  if is_dev else None,
        openapi_url="/openapi.json" if is_dev else None,
        lifespan=lifespan,
    )

    # ── Middleware ─────────────────────────────────────────────────────────────
    origins = cfg.cors_origins or ["http://localhost:5173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id", "x-trace-id"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # ── Request timing ─────────────────────────────────────────────────────────
    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        t0       = time.perf_counter()
        response = await call_next(request)
        ms       = round((time.perf_counter() - t0) * 1000, 2)
        response.headers["x-process-time"] = f"{ms}ms"
        if ms > 2000:
            logger.warning("Slow request: %s %s took %.0fms", request.method, request.url.path, ms)
        return response

    # ── Static files ───────────────────────────────────────────────────────────
    # import os
    # from fastapi.staticfiles import StaticFiles
    # os.makedirs("uploads/products", exist_ok=True)
    # os.makedirs("uploads/misc", exist_ok=True)
    # app.mount("/static/products", StaticFiles(directory="uploads/products"), name="products")
    # app.mount("/static",          StaticFiles(directory="uploads"),          name="static")

    # ── Exception handlers ─────────────────────────────────────────────────────
    setup_exception_handlers(app)

    # ── Routers ────────────────────────────────────────────────────────────────
    prefix = cfg.general_config.api_prefix
    app.include_router(root_router)
    app.include_router(v1_router, prefix=prefix)

    logger.info("Stitch API ready — %d routes registered.", len(app.routes))
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    cfg = get_app_config()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=cfg.hosting_config.port,
        reload=cfg.general_config.development_mode,
        log_level="info",
    )

