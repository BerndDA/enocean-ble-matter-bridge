#!/bin/sh
# Render the case: STLs for printing and preview PNGs, into case/.
#   tools/export_case.sh [extra openscad -D options, e.g. -D 'inner_h=5.5']
set -e
cd "$(dirname "$0")/../case"
SCAD=${OPENSCAD:-openscad}
for part in base lid pin; do
  "$SCAD" -q "$@" -D "part=\"$part\"" -o "bridge_case-$part.stl" bridge_case.scad
  echo "case/bridge_case-$part.stl"
done
"$SCAD" -q "$@" -D 'part="assembly"' --render --imgsize=1600,1200 --colorscheme=Tomorrow \
  --camera=31,15,10,55,0,30,165 -o bridge_case-assembly.png bridge_case.scad
"$SCAD" -q "$@" -D 'part="assembly"' --render --imgsize=1600,1200 --colorscheme=Tomorrow \
  --camera=31,15,10,55,0,210,165 -o bridge_case-assembly-back.png bridge_case.scad
echo "case/bridge_case-assembly.png, case/bridge_case-assembly-back.png"
