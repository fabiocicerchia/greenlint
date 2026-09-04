# Minimal image for running greenlint as a CLI (e.g. in CI).
# greenlint has no runtime dependencies, so this stays small.

# --- build stage ---
FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 AS build
WORKDIR /src
COPY . .
# The build backend comes from a hash-pinned lockfile and isolation is off, so
# building the wheel fetches nothing. `pip wheel` on its own would still be
# reported as pinned while PEP 517 isolation quietly downloaded setuptools
# from PyPI -- Scorecard cannot see inside pip, which makes that a silenced
# finding rather than a pinned build.
RUN pip install --no-cache-dir --require-hashes -r requirements-build.txt \
 && pip wheel --no-cache-dir --no-build-isolation --no-deps -w dist .

# --- runtime stage ---
FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6
WORKDIR /app
RUN useradd -u 10001 -m app
COPY --from=build /src/dist/*.whl /tmp/
# --no-deps: the wheel is the only thing meant to land here.
RUN pip install --no-cache-dir --no-deps /tmp/*.whl && rm /tmp/*.whl
USER app
# hardener: run this image with `docker run --read-only` for a read-only rootfs

# One-shot CLI tool, not a service — this just confirms the interpreter starts.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=1 \
    CMD ["python3", "-c", "import sys; sys.exit(0)"]

ENTRYPOINT ["greenlint"]
CMD ["--help"]
