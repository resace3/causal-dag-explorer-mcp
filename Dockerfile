# Build the frontend, then serve it from the Python backend on a single port.

FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY server/pyproject.toml ./server/pyproject.toml
COPY server/app ./server/app
RUN pip install ./server

COPY config.example.yaml ./config.example.yaml
COPY --from=frontend /build/dist ./frontend/dist

# Loopback only unless API_HOST is overridden by the compose file.
ENV API_HOST=127.0.0.1 API_PORT=8000 DATA_DIR=/data
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "server", "--host", "0.0.0.0", "--port", "8000"]
