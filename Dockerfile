# Minimal image for running greenlint as a CLI (e.g. in CI).
# greenlint has no runtime dependencies, so this stays small.

# --- build stage ---
FROM python:3.12-slim AS build
WORKDIR /src
COPY . .
RUN pip install --no-cache-dir build && python -m build --wheel

# --- runtime stage ---
FROM python:3.12-slim
WORKDIR /app
RUN useradd -u 10001 -m app
COPY --from=build /src/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
USER app

# One-shot CLI tool, not a service — this just confirms the interpreter starts.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=1 \
    CMD ["python3", "-c", "import sys; sys.exit(0)"]

ENTRYPOINT ["greenlint"]
CMD ["--help"]
