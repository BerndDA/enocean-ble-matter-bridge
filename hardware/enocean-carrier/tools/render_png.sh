#!/bin/sh
# Render pictures of the design:
#   enocean-carrier.png          the schematic (A3)
#   enocean-carrier-top.png      3D render of the board, top side
#   enocean-carrier-bottom.png   3D render of the board, bottom side
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
"$CLI" sch export pdf -o "$TMP/sch.pdf" enocean-carrier.kicad_sch >/dev/null 2>&1
pdftoppm -r "$DPI" -png -singlefile "$TMP/sch.pdf" enocean-carrier
echo "enocean-carrier.png ($DPI dpi)"

if [ -f enocean-carrier.kicad_pcb ]; then
  for side in top bottom; do
    "$CLI" pcb render --side $side --width 2400 --height 1000 --zoom 1.15 --quality high \
      -o "enocean-carrier-$side.png" enocean-carrier.kicad_pcb >/dev/null 2>&1
    echo "enocean-carrier-$side.png"
  done
fi
