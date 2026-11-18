#!/bin/sh
# Render pictures of the design:
#   enocean-bridge.png          the schematic (A3)
#   enocean-bridge-top.png      3D render of the board, top side
#   enocean-bridge-bottom.png   3D render of the board, bottom side
#
#   tools/render_png.sh [dpi]        (schematic dpi, default 200)
#
# Needs KiCad (kicad-cli) and poppler (pdftoppm: brew install poppler).
set -e
cd "$(dirname "$0")/.."
DPI=${1:-200}
CLI=${KICAD_CLI:-/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli}
command -v pdftoppm >/dev/null || { echo "pdftoppm missing: brew install poppler" >&2; exit 1; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
"$CLI" sch export pdf -o "$TMP/sch.pdf" enocean-bridge.kicad_sch >/dev/null 2>&1
pdftoppm -r "$DPI" -png -singlefile "$TMP/sch.pdf" enocean-bridge
echo "enocean-bridge.png ($DPI dpi)"

if [ -f enocean-bridge.kicad_pcb ]; then
  for side in top bottom; do
    "$CLI" pcb render --side $side --width 2400 --height 1000 --zoom 2.2 --quality high \
      -o "enocean-bridge-$side.png" enocean-bridge.kicad_pcb >/dev/null 2>&1
    echo "enocean-bridge-$side.png"
  done
fi
