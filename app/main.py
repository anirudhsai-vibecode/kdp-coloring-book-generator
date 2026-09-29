"""FastAPI application for KDP Coloring Book Generator."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure src/ is on path for kdp_coloring imports
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router as api_router
from app.api.credentials import router as credentials_router
from app.api.auth import router as auth_router
from app.core.config import settings, get_output_path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Templates
templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
templates.env.cache = None  # Disable cache to avoid jinja2 3.1+ cache bug


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting %s", settings.app_name)
    output_dir = get_output_path()
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Output directory: %s", output_dir)

    yield

    # Shutdown
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        description="KDP Coloring Book Generator API - Async book generation with Cloudflare Workers AI",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(auth_router)
    app.include_router(api_router)
    app.include_router(credentials_router)

    # Frontend route
    @app.get("/")
    async def frontend(request: Request):
        logger.info("Frontend route called")
        return templates.TemplateResponse(request, "index.html", {"request": request})

    # Health check endpoint
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": settings.app_name}

    # Serve static files
    static_dir = ROOT / "app" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    output_dir = get_output_path()
    if output_dir.exists():
        app.mount("/output", StaticFiles(directory=str(output_dir)), name="output")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )