FROM python:3.12-slim

WORKDIR /app

# Install uv for faster dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml ./

# Install dependencies
RUN uv sync --no-dev --no-install-project

# Copy source code
COPY src/ src/

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import src; print('ok')" || exit 1

# Default: HTTP mode for container deployment
ENV TRANSPORT=streamable-http
ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8000

EXPOSE 8000

CMD ["uv", "run", "python", "-m", "src.server", "--transport", "streamable-http", "--port", "8000"]
