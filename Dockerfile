FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1

# Only what the deployable needs; tests, the app and docs stay out of the image (.dockerignore).
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY services ./services
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "--no-sync", "archie-launch"]
