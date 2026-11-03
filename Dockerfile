FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1

# Only what the deployable needs; tests, the app and docs stay out of the image (.dockerignore).
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY services ./services
# The testing package is a workspace member but dev-only (it pulls pytest), so it stays out of the image.
RUN uv sync --frozen --no-dev --no-install-package archie-testing

CMD ["uv", "run", "--no-sync", "archie-launch"]
