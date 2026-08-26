# Stage 1: build the dashboard
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend .
RUN npm run build

# Stage 2: Python runtime serving API + built dashboard
FROM python:3.12-slim
WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY data data
COPY scripts scripts
COPY --from=ui /ui/dist frontend/dist
EXPOSE 8000
CMD python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}
