"""FastAPI app factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.aggregators.scoring.scoring import load_weights
from app.api import routes_cases, routes_listing, routes_stream
from app.core.agent import AgentContext
from app.core.factory import build_context
from app.core.settings import Settings, get_settings
from app.orchestrator.conversation import InvalidActionError
from app.orchestrator.events import EventBus
from app.orchestrator.registry import build_agents
from app.orchestrator.service import (
    CaseClosedError,
    CaseNotFoundError,
    CaseService,
    UploadConflictError,
)
from app.storage.memory import InMemoryCaseRepo
from app.storage.mongo import MongoCaseRepo
from app.storage.repository import CaseRepository


def _build_repo(settings: Settings) -> CaseRepository:
    if settings.storage == "mongo":
        return MongoCaseRepo(settings.mongodb_uri, settings.mongodb_db)
    return InMemoryCaseRepo()


async def _check_storage(repo: CaseRepository, ctx: AgentContext) -> None:
    """With Mongo storage, ping the cluster at startup so a bad URI fails now, not mid-demo."""
    if not isinstance(repo, MongoCaseRepo):
        return
    try:
        await repo.ping()
    except Exception:
        ctx.log.exception("MongoDB is unreachable: check MONGODB_URI in .env")
        raise


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app: settings, repo, event bus, agents, context and CaseService on app.state."""
    settings = settings or get_settings()
    ctx = build_context(settings)
    repo = _build_repo(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await _check_storage(repo, ctx)
        yield
        await app.state.service.shutdown()
        await ctx.http.aclose()
        if isinstance(repo, MongoCaseRepo):
            repo.close()

    app = FastAPI(title="Rental Scam Shield", lifespan=lifespan)
    bus = EventBus()
    app.state.settings = settings
    app.state.bus = bus
    app.state.service = CaseService(
        repo=repo,
        bus=bus,
        agents=build_agents(settings),
        ctx=ctx,
        weights=load_weights(),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(CaseNotFoundError)
    async def _not_found(_: Request, exc: CaseNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"case not found: {exc}"})

    @app.exception_handler(CaseClosedError)
    async def _closed(_: Request, exc: CaseClosedError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": f"case already decided: {exc}"})

    @app.exception_handler(InvalidActionError)
    async def _bad_action(_: Request, exc: InvalidActionError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(UploadConflictError)
    async def _upload_conflict(_: Request, exc: UploadConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    app.include_router(routes_cases.router)
    app.include_router(routes_stream.router)
    app.include_router(routes_listing.router)
    return app


app = create_app()
