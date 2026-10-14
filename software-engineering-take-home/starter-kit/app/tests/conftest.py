"""Test wiring.

Every external dependency is substituted; nothing here reaches the network or spends a cent
(constitution Principles III and VI). What is deliberately *not* faked: the cost table, the
coverage table and the 30-record knowledge base are the real files, because faking them would
make every arithmetic and retrieval assertion a tautology.

A fixed clock and a counter id factory are what make trace assertions exact.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
STARTER_KIT = APP_ROOT.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from claim_triage.deps import Deps  # noqa: E402
from claim_triage.main import create_app  # noqa: E402
from claim_triage.rag.corpus import load_knowledge_base  # noqa: E402
from claim_triage.rag.ingest import ingest  # noqa: E402
from claim_triage.rag.store_qdrant import QdrantStore  # noqa: E402
from claim_triage.settings import Settings  # noqa: E402
from claim_triage.store.reports import InMemoryReportStore  # noqa: E402
from claim_triage.tools.tables import CostTable, CoverageTable  # noqa: E402
from tests.fakes import FakeEmbedder, fake_llm  # noqa: E402

# Paths are resolved from the repository layout, so the suite runs identically in the image
# (where /app/data/knowledge-base is mounted) and on a developer machine.
DATA_DIR = STARTER_KIT / "data"
TOOLS_DIR = STARTER_KIT / "tools"
CONTRACT_PATH = STARTER_KIT / "api-contract" / "openapi.yaml"
IN_IMAGE_DATA = Path("/app/data/knowledge-base")
IN_IMAGE_TOOLS = Path("/app/tools")
IN_IMAGE_CONTRACT = Path("/app/api-contract/openapi.yaml")
IN_IMAGE_IMAGES = Path("/app/data/test-images")
IN_IMAGE_DOCUMENTS = Path("/app/data/test-documents")

FIXED_NOW = datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)
#: A dummy that is obviously not a real credential, so a leak in a test is unmistakable.
TEST_CREDENTIAL = "sk-test-not-a-real-key-0000"


def _knowledge_base_dir() -> Path:
    return IN_IMAGE_DATA if IN_IMAGE_DATA.is_dir() else DATA_DIR / "knowledge-base"


def _tools_dir() -> Path:
    return IN_IMAGE_TOOLS if IN_IMAGE_TOOLS.is_dir() else TOOLS_DIR


def contract_path() -> Path:
    return IN_IMAGE_CONTRACT if IN_IMAGE_CONTRACT.is_file() else CONTRACT_PATH


@pytest.fixture(scope="session")
def test_images_dir() -> Path:
    """Development photo fixtures, mounted read-only for the test run (see the Makefile)."""
    local = DATA_DIR / "test-images"
    return IN_IMAGE_IMAGES if IN_IMAGE_IMAGES.is_dir() else local


@pytest.fixture(scope="session")
def test_documents_dir() -> Path:
    local = DATA_DIR / "test-documents"
    return IN_IMAGE_DOCUMENTS if IN_IMAGE_DOCUMENTS.is_dir() else local


@pytest.fixture(scope="session")
def knowledge_base() -> dict[str, dict[str, Any]]:
    records = load_knowledge_base(_knowledge_base_dir())
    assert records, f"knowledge base not found at {_knowledge_base_dir()}"
    return records


@pytest.fixture(scope="session")
def cost_table() -> CostTable:
    return CostTable.load(_tools_dir())


@pytest.fixture(scope="session")
def coverage_table() -> CoverageTable:
    return CoverageTable.load(_tools_dir())


@pytest.fixture
def settings() -> Settings:
    return Settings(
        portkey_api_key=TEST_CREDENTIAL,
        portkey_base_url="https://portkey.example/v1",
        claude_model_route="@anthropic---test/claude-opus-5",
        knowledge_base_dir=_knowledge_base_dir(),
        tools_dir=_tools_dir(),
        openapi_path=contract_path(),
        app_env="test",
        request_budget_s=30.0,
    )


@pytest.fixture
def clock():
    """Monotonic, advancing 10 ms per read, so durations are positive and deterministic."""
    state = {"now": FIXED_NOW}

    def _now() -> datetime:
        state["now"] = state["now"] + timedelta(milliseconds=10)
        return state["now"]

    return _now


@pytest.fixture
def ids():
    counter = {"n": 0}

    def _next() -> str:
        counter["n"] += 1
        return f"claim-{counter['n']:04d}"

    return _next


@pytest.fixture
def vectors(settings, knowledge_base, embedder) -> QdrantStore:
    """In-memory Qdrant holding the real corpus (research D13)."""
    store = QdrantStore.in_memory()
    store.ensure_collection(settings.collection_name, embedder.dimension)
    return store


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def llm():
    """The default script: clean intake, a full loop, one clean safety verdict."""
    return fake_llm()


@pytest.fixture
def make_deps(settings, embedder, vectors, cost_table, coverage_table, clock, ids, knowledge_base):
    """Build Deps with any part overridden, then populate the vector store."""

    def _make(**overrides: Any) -> Deps:
        # Popped first: a test that supplies its own (empty or broken) store must be able to
        # opt out of population, and the strict-overrides assertion below would reject it.
        skip_ingest = overrides.pop("skip_ingest", False)
        deps = Deps(
            settings=overrides.pop("settings", settings),
            llm=overrides.pop("llm", fake_llm()),
            embedder=overrides.pop("embedder", embedder),
            vectors=overrides.pop("vectors", vectors),
            cost_table=overrides.pop("cost_table", cost_table),
            coverage_table=overrides.pop("coverage_table", coverage_table),
            reports=overrides.pop("reports", InMemoryReportStore()),
            clock=overrides.pop("clock", clock),
            new_id=overrides.pop("new_id", ids),
            knowledge_base=overrides.pop("knowledge_base", knowledge_base),
        )
        assert not overrides, f"unknown Deps overrides: {sorted(overrides)}"
        if not skip_ingest:
            ingest(deps)
        return deps

    return _make


@pytest.fixture
def deps(make_deps, llm) -> Deps:
    return make_deps(llm=llm)


@pytest.fixture
def client(deps) -> TestClient:
    return TestClient(create_app(deps))


@pytest.fixture
def make_client(make_deps):
    def _make(**overrides: Any) -> tuple[TestClient, Deps]:
        built = make_deps(**overrides)
        return TestClient(create_app(built)), built

    return _make


@pytest.fixture
def damage_photo(test_images_dir) -> bytes:
    return (test_images_dir / "IMG_001.jpg").read_bytes()


@pytest.fixture
def inspection_pdf(test_documents_dir) -> bytes:
    return (test_documents_dir / "IMG_001-inspection.pdf").read_bytes()


@pytest.fixture
def quote_pdf(test_documents_dir) -> bytes:
    return (test_documents_dir / "IMG_001-repair-estimate.pdf").read_bytes()


def submit(client: TestClient, **kwargs: Any):
    """Post a submission the way a client does, including the text-only multipart shape."""
    images = kwargs.pop("images", None)
    description = kwargs.pop("description", None)
    document = kwargs.pop("document", None)
    policy_type = kwargs.pop("policy_type", None)
    assert not kwargs, f"unknown submit arguments: {sorted(kwargs)}"

    files: list[tuple[str, tuple[str | None, Any, str]]] = []
    for index, raw in enumerate(images or []):
        files.append(("images", (f"view-{index}.jpg", raw, "image/jpeg")))
    if document is not None:
        files.append(("document", ("inspection.pdf", document, "application/pdf")))
    data: dict[str, str] = {}
    if description is not None:
        data["description"] = description
    if policy_type is not None:
        data["policy_type"] = policy_type
    return client.post("/api/v1/claims/triage", data=data or None, files=files or None)
