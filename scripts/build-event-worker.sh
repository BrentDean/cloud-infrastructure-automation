#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <output-binary>" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/services/event-worker"
OUTPUT="$1"
mkdir -p "$(dirname "$OUTPUT")"

go_is_compatible() {
  command -v go >/dev/null 2>&1 || return 1
  python3 - "$(go env GOVERSION 2>/dev/null || true)" <<'PY'
import re
import sys
match = re.fullmatch(r"go(\d+)\.(\d+)(?:\.\d+)?", sys.argv[1])
raise SystemExit(0 if match and (int(match.group(1)), int(match.group(2))) >= (1, 26) else 1)
PY
}

if go_is_compatible; then
  (
    cd "$SOURCE"
    GOTOOLCHAIN=auto CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
      go build -trimpath -ldflags='-s -w' -o "$OUTPUT" .
  )
elif command -v docker >/dev/null 2>&1; then
  docker info >/dev/null || {
    echo "Docker is installed but its daemon is unavailable." >&2
    exit 1
  }
  docker run --rm --platform linux/amd64 \
    --user "$(id -u):$(id -g)" \
    -e GOCACHE=/tmp/go-build -e GOMODCACHE=/tmp/go-mod \
    -v "$SOURCE:/src:ro" -v "$(dirname "$OUTPUT"):/out" \
    -w /src golang:1.26-alpine \
    sh -lc "go mod download && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o /out/$(basename "$OUTPUT") ."
else
  echo "Need Go 1.26+ or a working Docker daemon to build the event worker." >&2
  exit 1
fi

test -s "$OUTPUT"
file "$OUTPUT" | grep -q 'ELF 64-bit.*x86-64' || {
  echo "Event worker is not a Linux amd64 ELF binary." >&2
  exit 1
}
chmod 0755 "$OUTPUT"
echo "Built event worker: $OUTPUT"
