#!/bin/bash
# Single entry point; compatible with macOS Bash 3.2 and Linux Bash.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
cd "$ROOT"
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
Usage: bash run_comparison.sh [--local] [--build] [--no-open] [ACTION]

Default: preflight (no full Lituya water cases).
  preflight  Verify image, run tiny synthetic executable tests, prepare and audit
             exactly three common-source input decks. Produces a small ZIP.
  run        Execute only cap_050, cap_100, cap_200 from a passed preflight.
             Refuses changed settings, old outputs, or a different solver/image.
  collect    Collect existing comparison diagnostics; no water calculation.
  status     Print existing comparison status; no water calculation.

Start here: bash run_comparison.sh preflight
After review: bash run_comparison.sh run

No grid, duration, source, cap-list, or calibration overrides are accepted.
Use this in the separately extracted Lituya_Cap_Comparison folder.
Keep the original project and its run files unchanged.
HELP
      exit 0 ;;
    *) break ;;
  esac
done
ACTION="${1:-preflight}"
case "$ACTION" in preflight|run|collect|status) ;; *) echo "Unknown action: $ACTION. Use --help." >&2; exit 2;; esac
if [ "$#" -eq 0 ]; then set -- preflight; fi
if [ "$#" -ne 1 ]; then echo "This fixed experiment accepts one action only; no parameter overrides." >&2; exit 2; fi
# These two actions are read-only inspections of existing records and need no Docker.
if [ "$ACTION" = collect ] || [ "$ACTION" = status ]; then LOCAL=1; fi
mkdir -p comparison_logs
STAMP="$(date -u +%Y%m%dT%H%M%SZ)_$$"
LOG="comparison_logs/${STAMP}_${ACTION}.log"
if [ "$LOCAL" = 1 ]; then
  PYTHON="${PYTHON:-python3}"
  command -v "$PYTHON" >/dev/null 2>&1 || { echo "Python not found: $PYTHON" >&2; exit 1; }
  set +e
  ENTRY="$ROOT/comparison.py"
  case "$ACTION" in collect|status) ENTRY="$ROOT/collect_comparison.py";; esac
  "$PYTHON" -u "$ENTRY" "$@" 2>&1 | tee "$LOG"
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
  IMAGE="${LITUYA_IMAGE:-lituya-cap-comparison:${TARGET}-dev3-$ARCH}"
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
    IIDFILE="$ROOT/comparison_logs/${STAMP}_${TARGET}.image-id"
    "${D[@]}" build --progress=plain --platform "linux/$ARCH" --target "$TARGET" \
      --iidfile "$IIDFILE" -t "$IMAGE" . 2>&1 | tee "comparison_logs/${STAMP}_build.log"
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
    -v "$ROOT:/workspace" -w /workspace -e LITUYA_ROOT=/workspace -e LITUYA_RUN_IMAGE_ID="$RUN_IMAGE" \
    -e HOME=/tmp -e MPLBACKEND=Agg -e MPLCONFIGDIR=/tmp/lituya-matplotlib \
    -e OMP_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 \
    --entrypoint python "$RUN_IMAGE" -u /workspace/comparison.py "$@" 2>&1 | tee "$LOG"
  STATUS=${PIPESTATUS[0]}
  set -e
fi
if [ "$STATUS" -ne 0 ]; then
  echo "Stopped with exit $STATUS. Keep $LOG; inspect comparison_runs and upload the comparison diagnostics ZIP or the log." >&2
  exit "$STATUS"
fi
echo "Comparison records are in: $ROOT/comparison_runs"
echo "The original project and its runs have not been modified."
