# =============================================================================
# Dockerfile — Text-to-Image with Prompt Assist
# =============================================================================
#
# This is a "multi-stage" build.  Think of it like a two-step recipe:
#
#   Stage 1 ("builder"):  Install all Python packages into a virtual
#       environment.  This stage is thrown away after the build — its only
#       job is to produce the installed packages.
#
#   Stage 2 ("runtime"):  Copy the installed packages from Stage 1 into a
#       clean, slim image that contains only what the app needs to run.
#
# Why bother?  Stage 1 needs compilers and build tools (large).  Stage 2
# doesn't — so the final image is much smaller.
#
# This Dockerfile installs the full CUDA-enabled PyTorch by default for
# GPU-accelerated inference.  For a smaller CPU-only image, see the
# comments marked "CPU VARIANT" below.
# =============================================================================


# ---------------------------------------------------------------------------
# Stage 1: Builder — install Python dependencies
# ---------------------------------------------------------------------------
# "python:3.12-slim" is a minimal Debian image with Python pre-installed.
# We use it as a throwaway environment to compile / install packages.
FROM python:3.12-slim AS builder

# Create a virtual environment inside the container.  This keeps all
# installed packages in one directory (/opt/venv) that we can copy later.
RUN python -m venv /opt/venv

# Make the venv's python/pip the default for all subsequent RUN commands.
ENV PATH="/opt/venv/bin:$PATH"

# Copy only the requirements file first.  Docker caches each step — if
# requirements.txt hasn't changed, Docker skips re-installing packages.
# This makes rebuilds much faster when you only change source code.
COPY requirements.txt .

# Install dependencies.
#   --no-cache-dir : don't store pip's download cache (saves space)
#
# This installs the full CUDA-enabled PyTorch (~2 GB).  The PyTorch wheel
# bundles its own CUDA runtime, so the base image doesn't need CUDA — only
# the NVIDIA driver on the host machine is required.
#
# CPU VARIANT: To build a smaller image without GPU support, replace the
# line below with:
#   RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
#       && pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements.txt


# ---------------------------------------------------------------------------
# Stage 2: Runtime — the final, slim image
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Labels help identify the image in registries and tooling.
LABEL maintainer="text-to-image"
LABEL description="Text-to-Image with Prompt Assist API service"

# Copy the fully-installed virtual environment from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Put the venv on PATH so "python" and "uvicorn" resolve correctly.
ENV PATH="/opt/venv/bin:$PATH"

# Tell Python not to buffer stdout/stderr.  Without this, log messages
# can get stuck in a buffer and never appear in `docker logs`.
ENV PYTHONUNBUFFERED=1

# Tell Python not to write .pyc files.  Saves a tiny bit of disk space
# and avoids permission issues.
ENV PYTHONDONTWRITEBYTECODE=1

# HuggingFace downloads models to a cache directory.  We set it explicitly
# so it's easy to mount as a volume (avoids re-downloading ~4 GB every
# time the container restarts).
ENV HF_HOME=/data/huggingface

# Create a non-root user.  Running as root inside a container is a
# security risk — if an attacker escapes the app, they'd have root on
# the host.  This user has no password and no home directory.
RUN useradd --create-home --shell /bin/bash appuser

# Create the HuggingFace cache directory and give our user ownership.
RUN mkdir -p /data/huggingface && chown appuser:appuser /data/huggingface

# Set the working directory.  All subsequent COPY and RUN commands, and
# the final CMD, run relative to this path.
WORKDIR /app

# Copy the application source code into the image.
COPY --chown=appuser:appuser main.py configuration.py ./
COPY --chown=appuser:appuser application/ ./application/

# Switch to the non-root user for all subsequent commands.
USER appuser

# Expose port 8000.  This is documentation — it tells anyone reading the
# Dockerfile (or tools like docker-compose) which port the app listens on.
# It does NOT actually publish the port; that's done with -p or in compose.
EXPOSE 8000

# Health check.  Docker (and orchestrators like Kubernetes) will
# periodically hit this endpoint.  If it fails, the container is
# marked unhealthy and can be restarted automatically.
#   --interval   : check every 30 seconds
#   --timeout    : give the request 10 seconds before considering it failed
#   --start-period: wait 120 seconds before the first check (the Stable
#                   Diffusion model takes a while to load on first start)
#   --retries    : mark unhealthy after 3 consecutive failures
#
# Uses /health/ready instead of /health so that the container is only
# marked healthy when both the language model client and the Stable
# Diffusion pipeline are initialised.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready')" || exit 1

# The command that runs when the container starts.
#
#   uvicorn            : the ASGI server that serves the FastAPI app
#   main:fastapi_application : import path (file:variable)
#   --host 0.0.0.0     : listen on ALL interfaces (required in containers;
#                         127.0.0.1 would only be reachable from inside)
#   --port 8000         : match the EXPOSE above
#   --timeout-graceful-shutdown 60 : give in-flight requests 60s to finish
#                                    when the container is stopped
CMD ["uvicorn", "main:fastapi_application", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "60"]
