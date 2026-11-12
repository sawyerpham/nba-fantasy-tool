# One image runs the whole app: the API (FastAPI) also serves the built frontend at /.
#   docker compose up --build        then open http://localhost:8000
# Pulled data lives in /data (a volume), Telegram keys come from backend/.env (see README).

# --- stage 1: build the frontend ---
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- stage 2: the API, with the built frontend ---
FROM python:3.13-slim
WORKDIR /app/backend
COPY shared/ /app/shared/
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=web /web/dist /app/frontend/dist
ENV DRAFT_ADVISOR_DATA_DIR=/data PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["python", "-m", "app.serve", "--host", "0.0.0.0", "--port", "8000"]
