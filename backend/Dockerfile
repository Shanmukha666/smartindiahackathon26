FROM python:3.11-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-dev

FROM python:3.11-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY classification.py ./classification.py
COPY classification_tree.yaml ./classification_tree.yaml
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
RUN groupadd --system app && useradd --system --gid app --home-dir /app app && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
