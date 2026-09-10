# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Baked into the image below so the first request does not pay for a
    # download, and so the container works with no egress to openaipublic.
    TIKTOKEN_CACHE_DIR=/opt/tiktoken

WORKDIR /app

# Installed from PyPI rather than copied from the astral-sh/uv image: that
# image lives on ghcr.io, and some build environments (restricted egress,
# registry allowlists) can pull from docker.io/pypi but not ghcr.io.
RUN pip install --no-cache-dir uv==0.5.11

# Dependencies resolve from pyproject.toml alone, so this layer survives every
# source change. `-r pyproject.toml` installs [project.dependencies] without
# building the project itself.
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml \
    && mkdir -p "$TIKTOKEN_CACHE_DIR" \
    && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Non-root: the app writes nothing outside /tmp, so there is no reason to hand it
# root in a container that talks to the internet.
RUN useradd --create-home --uid 10001 app \
    && chown -R app:app /app
USER app

EXPOSE 8000

# Liveness only, matching /health's contract: this must not check Postgres, or a
# thirty-second database blip restarts every replica and turns a dependency
# wobble into an outage.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request,sys; p=os.environ.get('PORT','8000'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+p+'/health', timeout=2).status == 200 else 1)"

# `exec` so uvicorn replaces the shell and stays PID 1: without it SIGTERM
# stops at the shell and the lifespan shutdown (engine dispose, storage close)
# never runs. The shell is needed at all because hosts like Render assign the
# port at runtime via $PORT; 8000 is the local default.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
