# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS dependencies
ARG TARGETARCH
RUN case "$TARGETARCH" in arm64|amd64) ;; *) echo "Unsupported CPU" >&2; exit 1;; esac
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/lituya-matplotlib HOME=/tmp \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
# Rasterio/GDAL needs this shared library in the slim Linux image.
# Install it here so the test stage and the runtime stage both inherit it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*
COPY environment/requirements*.txt /tmp/environment/
RUN python -m pip install --no-cache-dir --only-binary=:all: -r /tmp/environment/requirements-test.txt \
    && python -m pip check
# pip check validates package metadata, not whether native libraries can load.
RUN python -c 'import rasterio; print("Rasterio native import passed; GDAL=" + rasterio.__gdal_version__)'
WORKDIR /opt/lituya-bay
COPY . .

FROM dependencies AS tests
RUN python -m pytest
WORKDIR /workspace
ENTRYPOINT ["python", "-m", "pytest"]
CMD []

FROM tests AS runtime
ENV CLAW=/opt/clawpack PYTHONPATH=/opt/clawpack CLAW_PYTHON=/usr/local/bin/python FC=gfortran \
    LITUYA_SOLVER=/opt/lituya-bay/geoclaw/xgeoclaw \
    LITUYA_BUILD_MANIFEST=/opt/lituya-build-manifest.json
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git make gfortran gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch v5.14.0 --recurse-submodules --shallow-submodules https://github.com/clawpack/clawpack.git /opt/clawpack \
    && test "$(git -C /opt/clawpack describe --tags --exact-match)" = v5.14.0 \
    && git config --system --add safe.directory /opt/clawpack \
    && git -C /opt/clawpack submodule foreach --recursive 'git config --system --add safe.directory "$PWD"' \
    && python -c 'from clawpack.clawutil.data import ClawRunData; ClawRunData("geoclaw",2)'
WORKDIR /opt/lituya-bay
RUN make -C geoclaw .exe \
    && python -m tools.smoke --executable /opt/lituya-bay/geoclaw/xgeoclaw --report /opt/lituya-smoke.json \
    && python -m tools.image_manifest --smoke /opt/lituya-smoke.json --output /opt/lituya-build-manifest.json
# Atomic JSON writes start owner-only (0600). These two files contain public
# build metadata, so publish them read-only to the non-root runtime user.
# Do not change permissions on user outputs or disable the fingerprint checks.
RUN chmod 0644 /opt/lituya-build-manifest.json /opt/lituya-smoke.json
USER 1000:1000
# Test the permission boundary that root-only build tests cannot exercise.
# This uses the real launch verifier, followed by the real tiny solver test.
RUN python -c 'from simulation.common import ROOT, load; from simulation.runtime import solver; solver(load(ROOT / "config.json")); print("Non-root solver access check passed.")' \
    && python -m tools.smoke --executable /opt/lituya-bay/geoclaw/xgeoclaw --report /tmp/lituya-runtime-smoke.json
WORKDIR /workspace
ENTRYPOINT ["python", "-u", "/workspace/comparison.py"]
CMD ["--help"]
