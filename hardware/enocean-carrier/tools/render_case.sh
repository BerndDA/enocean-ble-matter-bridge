#!/bin/sh
# Photo-style renders of the carrier in its case: case/render-{closed,exploded,open}.png
#   tools/render_case.sh [samples]      (default 192; needs OpenSCAD, KiCad and Blender)
set -e
cd "$(dirname "$0")/.."
SAMPLES=${1:-192}
KICAD_CLI=${KICAD_CLI:-/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli}
BLENDER=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
for p in base lid_asm pin_asm; do
  openscad -q -D "part=\"$p\"" -o "$WORK/$p.stl" case/carrier_case.scad
done
"$KICAD_CLI" pcb export glb -f --no-dnp --include-tracks --include-pads --include-zones \
  --include-silkscreen --include-soldermask --user-origin 100x133.4mm \
  -o "$WORK/board.glb" enocean-carrier.kicad_pcb >/dev/null 2>&1
"$BLENDER" -b -P tools/render_case.py -- "$WORK" "$PWD/case" "$SAMPLES" 2>&1 | grep -E "^wrote|Error|Traceback|line [0-9]" || true
