#!/bin/sh
# Render the case: STLs for printing and preview PNGs, into case/.
#   tools/export_case.sh [extra openscad -D options, e.g. -D 'pm_mount="direct"']
# Two STL sets: carrier_case-<part>.stl for FDM, carrier_case-<part>-sla.stl for resin printers.
set -e
cd "$(dirname "$0")/../case"
SCAD=${OPENSCAD:-openscad}
for part in base lid pin plate; do
  "$SCAD" -q "$@" -D "part=\"$part\"" -o "carrier_case-$part.stl" carrier_case.scad
  "$SCAD" -q "$@" -D "part=\"$part\"" -D 'process="sla"' -o "carrier_case-$part-sla.stl" carrier_case.scad
  echo "case/carrier_case-$part.stl, case/carrier_case-$part-sla.stl"
done
"$SCAD" -q "$@" -D 'part="assembly"' --render --imgsize=1600,1200 --colorscheme=Tomorrow \
  --camera=26,19,10,55,0,30,150 -o carrier_case-assembly.png carrier_case.scad
"$SCAD" -q "$@" -D 'part="assembly"' --render --imgsize=1600,1200 --colorscheme=Tomorrow \
  --camera=26,19,10,55,0,210,150 -o carrier_case-assembly-back.png carrier_case.scad
echo "case/carrier_case-assembly.png, case/carrier_case-assembly-back.png"
