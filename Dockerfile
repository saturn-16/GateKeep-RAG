# Stage 1: Build Frontend UI
FROM node:18-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Production Python Backend
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src ./src
COPY scripts ./scripts
RUN pip install --no-cache-dir .

ENV PYTHONPATH=/app/src
ENV PERSISTENCE_BACKEND=postgres
ENV VECTOR_BACKEND=qdrant
ENV RUN_REAL_STACK=1

COPY alembic.ini ./
COPY alembic ./alembic
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8000

CMD ["sh", "-c", "if [ \"$PERSISTENCE_BACKEND\" = \"postgres\" ]; then alembic upgrade head && python scripts/seed_demo.py; fi; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
