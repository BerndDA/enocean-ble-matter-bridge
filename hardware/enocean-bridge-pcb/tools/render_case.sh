#!/bin/sh
# Photo-style renders of the bridge board in its case (Blender, Cycles):
#   tools/render_case.sh [samples]   stills case/render-{closed,exploded,open}.png (default 192 samples)
# Needs OpenSCAD, KiCad and Blender.
set -e
cd "$(dirname "$0")/.."
KICAD_CLI=${KICAD_CLI:-/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli}
BLENDER=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
for p in base lid_asm pin_asm; do
  openscad -q -D "part=\"$p\"" -o "$WORK/$p.stl" case/bridge_case.scad
done
# board origin (100, 100) on the KiCad canvas, 26 mm tall: lower-left corner at (100, 126)
"$KICAD_CLI" pcb export glb -f --no-dnp --include-tracks --include-pads --include-zones \
  --include-silkscreen --include-soldermask --user-origin 100x126mm \
  -o "$WORK/board.glb" enocean-bridge.kicad_pcb >/dev/null 2>&1
"$BLENDER" -b -P tools/render_case.py -- "$WORK" "$PWD/case" "${1:-192}" 2>&1 | grep -E "^wrote|Error|Traceback|line [0-9]" || true
