FROM python:3.11-slim-bullseye

# Build-time metadata
LABEL org.opencontainers.image.title="OilGas Nanobot Swarm"
LABEL org.opencontainers.image.description="NeuralQuantum hierarchical AI agent swarm for oil and gas engineering"
LABEL org.opencontainers.image.vendor="NeuralQuantum.ai LLC"
LABEL org.opencontainers.image.licenses="MIT"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1001 nanobot

WORKDIR /app

# Copy and install Python dependencies first (layer caching)
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# Copy application code
COPY --chown=nanobot:nanobot . .

# Create workspace directory
RUN mkdir -p /app/workspace && chown nanobot:nanobot /app/workspace

USER nanobot

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8100/health || exit 1

CMD ["python", "-m", "uvicorn", "nanobot.api.gateway:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
