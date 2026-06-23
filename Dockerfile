FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
ARG VITE_API_BASE=
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app/backend
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/novel_deconstructor /app/backend/novel_deconstructor
COPY examples /app/examples
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

WORKDIR /app/backend
EXPOSE 8000
CMD ["sh", "-c", "uvicorn novel_deconstructor.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
