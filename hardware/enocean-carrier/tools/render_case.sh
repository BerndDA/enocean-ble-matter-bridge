#!/bin/sh
# Photo-style renders of the carrier in its case (Blender):
#   tools/render_case.sh [samples]   stills case/render-{closed,exploded,open}.png (Cycles, default 192 samples)
#   tools/render_case.sh anim        assembly clip case/anim.mp4 (EEVEE, 8 s, 1280x720)
# Needs OpenSCAD, KiCad, Blender (and ffmpeg for the clip).
set -e
cd "$(dirname "$0")/.."
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
if [ "$1" = "anim" ]; then
  "$BLENDER" -b -P tools/render_case.py -- "$WORK" "$WORK" 64 anim 2>&1 | grep -E "^wrote|Error|Traceback|line [0-9]" || true
  ffmpeg -loglevel error -y -framerate 24 -i "$WORK/anim-frames/f%04d.png" \
    -c:v libx264 -pix_fmt yuv420p -crf 18 -movflags +faststart case/anim.mp4
  echo "case/anim.mp4"
else
  "$BLENDER" -b -P tools/render_case.py -- "$WORK" "$PWD/case" "${1:-192}" 2>&1 | grep -E "^wrote|Error|Traceback|line [0-9]" || true
fi
