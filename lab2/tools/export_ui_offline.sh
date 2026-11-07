#!/bin/sh
# Usage: sh export_ui_offline.sh /path/to/draw.io
# Native local export only. Remote access is disabled by an unusable local proxy.
set -eu
DRAWIO_BIN="$1"
LAB2_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
UI_SOURCE="$LAB2_ROOT/UI/校园循物_UI设计.drawio"
EXPORT_PDF="$LAB2_ROOT/local-build/ui-offline-export.pdf"
mkdir -p "$LAB2_ROOT/local-build"
"$DRAWIO_BIN" --disable-update --proxy-server=http://127.0.0.1:9 '--proxy-bypass-list=<-loopback>' \
  --export --all-pages --format pdf --crop --timeout 60 --output "$EXPORT_PDF" "$UI_SOURCE"
# The task used Poppler to convert this intermediate PDF to PNG at 2880px wide.
# Use each page's UI说明.json file name when replacing the final PNG.
