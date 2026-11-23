#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SOURCE="$PROJECT_DIR/launcher/jarvis_launcher.c"
OUTPUT="${1:-$PROJECT_DIR/dist/executable_x86_64/jarvis-local.x86_64}"
CC="${CC:-cc}"

mkdir -p "$(dirname -- "$OUTPUT")"
"$CC" \
  -std=c11 -O2 -Wall -Wextra -Werror \
  -fPIE -pie -s -fno-ident -fno-record-gcc-switches \
  -frandom-seed=jarvis-launcher \
  "-ffile-prefix-map=$PROJECT_DIR=." \
  -Wl,--build-id=none \
  "$SOURCE" -o "$OUTPUT"
