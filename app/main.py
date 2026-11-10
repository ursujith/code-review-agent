from __future__ import annotations

import hmac
import os
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.api.routes.reviews import router as reviews_router
from app.api.routes.gitlab import router as gitlab_router
from app.api.routes.webhooks import router as webhooks_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.agent import router as agent_router
from app.api.routes.admin import router as admin_router
from app.security.access_store import authenticate_token, init_access_store, list_tokens

try:
    from app.mcp_server import mcp
except ImportError:
    # API/web tests can still run in minimal environments; install project
    # dependencies to enable the remote MCP transport.
    mcp = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if mcp is None:
        yield
    else:
        async with mcp.session_manager.run():
            yield


app = FastAPI(
    title="AI Code Review Agent",
    description="Centralized AI code review backend with web and remote MCP access.",
    version="1.9.0",
    lifespan=lifespan,
)
app.include_router(reviews_router, prefix="/api/v1")
app.include_router(gitlab_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")

@app.on_event("startup")
async def initialize_agent_access_store():
    init_access_store()


@app.middleware("http")
async def protect_agent_access(request: Request, call_next):
    path = request.url.path
    admin_path = path.startswith("/api/v1/admin/agent-access/")
    protected = path.startswith("/api/v1/agent/") or path.startswith("/mcp") or admin_path
    if not protected:
        return await call_next(request)

    supplied = request.headers.get("authorization", "")
    prefix = "Bearer "
    provided = supplied[len(prefix):].strip() if supplied.startswith(prefix) else ""
    if admin_path:
        expected_admin = os.getenv("AGENT_ADMIN_TOKEN", "").strip()
        if not expected_admin:
            return JSONResponse(status_code=503, content={"detail": "Agent administration is not configured."})
        if not provided or not hmac.compare_digest(provided, expected_admin):
            return JSONResponse(status_code=401, content={"detail": "Invalid administrator token."})
        request.state.agent_username = "administrator"
        return await call_next(request)

    legacy = os.getenv("AGENT_ACCESS_TOKEN", "").strip()
    username = "legacy-shared-token" if legacy and provided and hmac.compare_digest(provided, legacy) else None
    if username is None:
        username = authenticate_token(provided)
    if username is None:
        if not legacy and not list_tokens():
            return JSONResponse(status_code=503, content={"detail": "Central agent access is not configured. Issue a developer token or configure AGENT_ACCESS_TOKEN."})
        return JSONResponse(status_code=401, content={"detail": "Invalid or revoked agent access token."})
    request.state.agent_username = username
    return await call_next(request)


@app.get("/", include_in_schema=False)
async def web_application():
    return FileResponse(Path(__file__).resolve().parent / "web" / "index.html")


@app.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Keep stdio MCP support for local Kiro, and expose the same tools over
# Streamable HTTP for Kiro installations on other laptops.
if mcp is not None:
    app.mount("/mcp", mcp.streamable_http_app())
