FROM node:24-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS python-build
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY sentinel/ ./sentinel/
COPY scripts/build_agent.py ./scripts/build_agent.py
RUN python scripts/build_agent.py

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    PATH="/opt/venv/bin:$PATH" SENTINEL_DATA=/data SENTINEL_SECURE_COOKIE=1
WORKDIR /app
RUN groupadd --gid 10001 sentinel && useradd --uid 10001 --gid sentinel --no-create-home sentinel \
    && mkdir /data && chown sentinel:sentinel /data
COPY --from=python-build /opt/venv /opt/venv
COPY --from=python-build /app/sentinel ./sentinel
COPY --from=python-build /app/dist ./dist
COPY --from=web /web/dist ./frontend/dist
COPY scripts/install-agent.sh scripts/uninstall-agent.sh ./scripts/
USER 10001:10001
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)" || exit 1
CMD ["python", "-m", "sentinel.server", "--host", "0.0.0.0", "--port", "8080"]
