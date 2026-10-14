FROM python:3.12-slim

# Test dependencies ship in this image on purpose: `make test` must run the project's own
# suite in the same environment the service runs in, with no second build target to drift.
# See plan.md Complexity Tracking.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    FASTEMBED_CACHE_DIR=/opt/fastembed

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

# Bake the embedding model into the image so the first container start needs no download
# (research D7). An explicit cache_dir is used rather than an env-var name that has moved
# between fastembed releases.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/fastembed')"

COPY pyproject.toml ./
COPY src/ ./src/
COPY tests/ ./tests/

EXPOSE 8000
CMD ["uvicorn", "--factory", "claim_triage.main:build_production_app", "--host", "0.0.0.0", "--port", "8000"]
