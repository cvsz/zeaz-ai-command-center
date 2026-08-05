FROM python:3.13-slim AS runtime

ARG APP_VERSION=3.4.3
LABEL org.opencontainers.image.title="ZEAZ AI Command Center" \
      org.opencontainers.image.description="Provider-agnostic AI CLI command builder and execution control panel" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.source="https://github.com/cvsz/zeaz-ai-command-center" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PANEL_HOST=0.0.0.0 \
    PANEL_PORT=8765 \
    PANEL_ALLOWED_HOSTS=localhost,127.0.0.1 \
    PANEL_ALLOWED_ROOTS=/workspace \
    PANEL_DATABASE_PATH=/data/jobs.sqlite3

RUN groupadd --system --gid 10001 commandcenter \
    && useradd --system --uid 10001 --gid commandcenter --home-dir /app --create-home commandcenter \
    && mkdir -p /app/static /app/examples /app/docs /data /workspace \
    && chown -R commandcenter:commandcenter /app /data /workspace

WORKDIR /app
COPY --chown=commandcenter:commandcenter server.py help_parser.py storage.py version.py gui.py zai.py pyproject.toml README.md CHANGELOG.md LICENSE ./
COPY --chown=commandcenter:commandcenter static ./static
COPY --chown=commandcenter:commandcenter examples ./examples
COPY --chown=commandcenter:commandcenter docs ./docs

USER commandcenter
EXPOSE 8765
VOLUME ["/data", "/workspace"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3).read()"

ENTRYPOINT ["python3", "server.py"]
CMD ["--host", "0.0.0.0", "--port", "8765"]
