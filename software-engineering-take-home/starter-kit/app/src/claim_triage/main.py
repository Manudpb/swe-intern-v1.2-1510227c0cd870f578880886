"""Application assembly.

`create_app(deps)` is the only way the app is built, and `build_deps` is the only place a
real provider is constructed. A request handler that built its own client would make the free
test suite impossible, which is why this separation is a constitution principle, not a style
preference (Principle VI).
"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

from claim_triage.api import routes_claims, routes_health, routes_trace
from claim_triage.deps import Deps
from claim_triage.rag.corpus import load_knowledge_base
from claim_triage.settings import Settings, install_credential_scrubber
from claim_triage.tools.tables import CostTable, CoverageTable

log = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_claim_id() -> str:
    return str(uuid.uuid4())


def create_app(deps: Deps) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if deps.settings.app_env != "test":
            from claim_triage.rag.ingest import ingest_with_retry

            ingest_with_retry(deps)
        yield

    app = FastAPI(
        title="Claim Triage API",
        version="1.0.0",
        description="AI-powered property damage claim triage system",
        lifespan=lifespan,
    )
    app.state.deps = deps
    app.include_router(routes_health.router, prefix="/api/v1")
    app.include_router(routes_claims.router, prefix="/api/v1")
    app.include_router(routes_trace.router, prefix="/api/v1")
    return app


def build_deps(settings: Settings) -> Deps:
    """Production wiring. The only constructor of real clients."""
    from claim_triage.llm.anthropic_portkey import AnthropicPortkeyClient
    from claim_triage.rag.embedder_fastembed import FastEmbedEmbedder
    from claim_triage.rag.store_qdrant import QdrantStore
    from claim_triage.store.reports import InMemoryReportStore

    install_credential_scrubber(settings)
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    return Deps(
        settings=settings,
        llm=AnthropicPortkeyClient(settings),
        embedder=FastEmbedEmbedder(settings.embedding_model, settings.fastembed_cache_dir),
        vectors=QdrantStore.from_url(settings.qdrant_url),
        cost_table=CostTable.load(settings.tools_dir),
        coverage_table=CoverageTable.load(settings.tools_dir),
        reports=InMemoryReportStore(),
        clock=utc_now,
        new_id=new_claim_id,
        knowledge_base=load_knowledge_base(settings.knowledge_base_dir),
    )


def build_production_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    log.info(
        "Starting claim triage API (llm=%s, qdrant=%s)",
        "configured" if settings.llm_configured else "not_configured",
        settings.qdrant_url,
    )
    return create_app(build_deps(settings))


# No module-level `app`: building one at import time would construct real clients (and need a
# credential) the moment pytest imports this module. Uvicorn is started with --factory instead.
