# AgroSense AI - single-service production image for Render
# Builds the React frontend and serves it from the FastAPI application.
FROM node:22-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DATA_MODE=REAL

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY data ./data
COPY models ./models
COPY --from=frontend-build /frontend/dist ./frontend-dist

EXPOSE 10000

# Render supplies PORT at runtime. Local fallback remains 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
