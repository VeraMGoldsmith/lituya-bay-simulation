#!/bin/bash
# Single entry point; compatible with macOS Bash 3.2 and Linux Bash.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
cd "$ROOT"
if [ -f "$ROOT/release/ISOLATED_COMPARISON" ] && [ "${1:-}" != --help ] && [ "${1:-}" != -h ]; then
  echo "This package is restricted to the 50/100/200 comparison. Use: bash run_comparison.sh preflight" >&2
  exit 2
fi
LOCAL=0
BUILD=0
OPEN=1
while [ "$#" -gt 0 ]; do
  case "$1" in
    --local) LOCAL=1; shift ;;
    --build) BUILD=1; shift ;;
    --no-open) OPEN=0; shift ;;
    -h|--help)
      cat <<'HELP'
Usage: bash run.sh [--local] [--build] [--no-open] [ACTION] [OPTIONS]

Default action: all
  all       Test coverage, baseline, nine source candidates, selected-run report
  baseline  Test coverage, prepare, stationary control, moving slide, report
  prepare   Test coverage and input inspection only; no water simulation
  test      Run the offline unit-test suite with a 90% coverage gate
  report    Rebuild the latest results page without rerunning the solver
  check     Verify the compiled GeoClaw executable and its build manifest

Options: --config PATH, --grid 15|30|60, --sw-relief-factor VALUE, --travel-m METRES,
         --duration-s SECONDS. Flags --local/--build/--no-open go before ACTION.

Examples:
  bash run.sh
  bash run.sh baseline
  bash run.sh --local test
  bash run.sh --no-open baseline --grid 60

Default execution uses Docker and checks the current Dockerfile on every run.
Unchanged layers can be cached; --build remains supported for compatibility.
--local uses an already prepared Python environment.
HELP
      exit 0 ;;
    *) break ;;
  esac
done
ACTION="${1:-all}"
case "$ACTION" in all|baseline|prepare|test|report|check) ;; *) echo "Unknown action: $ACTION. Use --help." >&2; exit 2;; esac
if [ "$#" -eq 0 ]; then set -- all; fi
mkdir -p logs
STAMP="$(date -u +%Y%m%dT%H%M%SZ)_$$"
LOG="logs/${STAMP}_${ACTION}.log"
if [ "$LOCAL" = 1 ]; then
  PYTHON="${PYTHON:-python3}"
  command -v "$PYTHON" >/dev/null 2>&1 || { echo "Python not found: $PYTHON" >&2; exit 1; }
  set +e
  "$PYTHON" -u "$ROOT/workflow.py" "$@" 2>&1 | tee "$LOG"
  STATUS=${PIPESTATUS[0]}
  set -e
else
  SYSTEM="$(uname -s)"
  case "$SYSTEM" in Darwin|Linux) ;; *) echo "This launcher supports macOS and Linux." >&2; exit 2;; esac
  ARCH="$(uname -m)"
  if [ "$SYSTEM" = Darwin ] && [ "$(sysctl -in sysctl.proc_translated 2>/dev/null || true)" = 1 ]; then ARCH=arm64; fi
  case "$ARCH" in arm64|aarch64) ARCH=arm64;; x86_64|amd64) ARCH=amd64;; *) echo "Unsupported CPU: $ARCH" >&2; exit 2;; esac
  export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin:$HOME/.docker/bin"
  command -v docker >/dev/null 2>&1 || { echo "Open Docker Desktop and complete its setup first." >&2; exit 1; }
  # Never send the bind-mounted working copy to an environment-selected remote host.
  unset DOCKER_HOST DOCKER_CONTEXT
  CONTEXT=default
  if docker context inspect desktop-linux >/dev/null 2>&1; then CONTEXT=desktop-linux; fi
  ENDPOINT="$(docker context inspect "$CONTEXT" --format '{{.Endpoints.docker.Host}}')"
  case "$ENDPOINT" in unix://*) ;; *) echo "A local Unix-socket Docker context is required; remote daemons are refused." >&2; exit 1;; esac
  D=(docker --context "$CONTEXT")
  "${D[@]}" info >/dev/null 2>&1 || { echo "Docker Engine is not ready. Leave Docker Desktop running." >&2; exit 1; }
  TARGET=runtime
  case "$ACTION" in test|prepare|report) TARGET=tests;; esac
  IMAGE="${LITUYA_IMAGE:-lituya-bay:${TARGET}-2.0.0-$ARCH}"
  echo "Project folder: $ROOT"
  if [ -n "${LITUYA_IMAGE:-}" ]; then
    # Explicit custom images are caller-managed. Do not silently rebuild them.
    FOUND="$("${D[@]}" image inspect --format '{{.Architecture}}' "$IMAGE" 2>/dev/null || true)"
    if [ "$BUILD" = 1 ] || [ "$FOUND" != "$ARCH" ]; then
      echo "Custom image is missing, has the wrong CPU, or --build was requested. Unset LITUYA_IMAGE to build the project image." >&2
      exit 1
    fi
    RUN_IMAGE="$("${D[@]}" image inspect --format '{{.Id}}' "$IMAGE")"
  else
    # Always submit the CURRENT Dockerfile to the builder. Merely finding a tag
    # with the right architecture does not establish that it includes updates.
    # Docker may reuse unchanged layers, but it evaluates changed instructions.
    echo "Checking/building the current Dockerfile (unchanged layers may be cached)."
    IIDFILE="$ROOT/logs/${STAMP}_${TARGET}.image-id"
    "${D[@]}" build --progress=plain --platform "linux/$ARCH" --target "$TARGET" \
      --iidfile "$IIDFILE" -t "$IMAGE" . 2>&1 | tee "logs/${STAMP}_build.log"
    if [ ! -s "$IIDFILE" ]; then
      echo "Build did not record an image ID. Refusing to run a previously cached image." >&2
      exit 1
    fi
    RUN_IMAGE="$(cat "$IIDFILE")"
  fi
  if ! printf '%s\n' "$RUN_IMAGE" | grep -Eq '^sha256:[0-9a-f]{64}$'; then
    echo "Docker did not provide a valid image ID. No calculation was started." >&2
    exit 1
  fi
  # Run the exact image produced by this build, not a mutable shared tag.
  echo "Using Docker image: $RUN_IMAGE"
  set +e
  "${D[@]}" run --rm --init --network none --platform "linux/$ARCH" \
    --user "$(id -u):$(id -g)" --cap-drop ALL --security-opt no-new-privileges:true \
    -v "$ROOT:/workspace" -w /workspace -e LITUYA_ROOT=/workspace \
    -e HOME=/tmp -e MPLBACKEND=Agg -e MPLCONFIGDIR=/tmp/lituya-matplotlib \
    -e OMP_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 \
    --entrypoint python "$RUN_IMAGE" -u /workspace/workflow.py "$@" 2>&1 | tee "$LOG"
  STATUS=${PIPESTATUS[0]}
  set -e
fi
if [ "$STATUS" -ne 0 ]; then
  echo "Stopped with exit $STATUS. Keep $LOG; inspect results/index.html and the current run diagnostics." >&2
  exit "$STATUS"
fi
if [ "$OPEN" = 1 ] && [ -f "$ROOT/results/index.html" ]; then
  case "$ACTION" in all|baseline|prepare|report)
    if [ "$(uname -s)" = Darwin ]; then open "$ROOT/results/index.html" || true
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$ROOT/results/index.html" >/dev/null 2>&1 || true
    fi ;;
  esac
fi
