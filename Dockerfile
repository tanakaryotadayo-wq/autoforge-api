FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/

# Install dependencies with uv
RUN uv pip install --system --no-cache .

# Expose port
EXPOSE 8698

# Run with Granian (not Uvicorn)
CMD ["granian", \
    "--interface", "asgi", \
    "--host", "0.0.0.0", \
    "--port", "8698", \
    "--workers", "2", \
    "autoforge.main:app"]
