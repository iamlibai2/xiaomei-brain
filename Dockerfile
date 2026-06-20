FROM python:3.12-slim

LABEL org.opencontainers.image.title="xiaomei-brain"
LABEL org.opencontainers.image.description="Multi-agent AI framework with consciousness, drive, purpose, and metacognition"

# System deps for building sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (layer caching)
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir . \
    && rm -rf /app/src /app/pyproject.toml /app/README.md

# Pre-download embedding model (makes first run instant)
RUN python3 -c "\
from contextlib import redirect_stderr; from io import StringIO; \
with redirect_stderr(StringIO()): \
    from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('BAAI/bge-m3'); \
"

# Clean up build deps
RUN apt-get purge -y gcc g++ && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

VOLUME /root/.xiaomei-brain
WORKDIR /root

ENTRYPOINT ["xiaomei-brain"]
CMD ["--help"]
