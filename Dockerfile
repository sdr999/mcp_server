# --- Production Dockerfile for MCP Server ---
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock

# Final runtime image
FROM python:3.12-slim

WORKDIR /app

# Create non-root system user
RUN groupadd -r mcpuser && useradd -r -g mcpuser -d /app mcpuser

# Copy installed packages from builder stage
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY src /app/src
COPY docs /app/docs
COPY openapi /app/openapi

# Set permissions
RUN mkdir -p /app/data /app/logs && \
    chown -R mcpuser:mcpuser /app

USER mcpuser

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["python", "-m", "main"]
