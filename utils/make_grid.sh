#!/usr/bin/env bash
# Make labelled calibration grids (1920x1080) to display on a screen at the Gear 360 lens seam.
# Magenta grid: vertices A1..O8. Green grid: vertices A9..O16 (row numbers continue, so labels are unique).
# Usage: utils/make_grid.sh [output_dir]   (default: the directory this script is in)
set -euo pipefail

outdir="${1:-$(dirname "$0")}"
mkdir -p "$outdir"

make_grid() {  # $1 = colour, $2 = row-number offset, $3 = output file
  local W=1920 H=1080 S=75 lines="" dots="" text="" col row
  for ((x=0; x<=W; x+=S)); do lines+="line $x,0 $x,$H "; done
  for ((y=0; y<=H; y+=S)); do lines+="line 0,$y $W,$y "; done
  for ((x=S; x<W; x+=S)); do
    for ((y=S; y<H; y+=S)); do
      col=$(printf "\\$(printf '%03o' $((64 + x/S)))")   # 1->A, 2->B, ...
      row=$(( y/S + $2 ))
      dots+="circle $x,$y $((x+7)),$y "
      text+="text $((x+10)),$((y-10)) '$col$row' "
    done
  done
  convert -size ${W}x${H} xc:black \
    -stroke "$1" -strokewidth 3 -fill none -draw "$lines" \
    -stroke none -fill "$1" -draw "$dots" \
    -pointsize 28 -fill "$1" -draw "$text" \
    "$3"
  echo "wrote $3"
}

make_grid magenta 0 "$outdir/grid_magenta.png"   # labels A1..O8
make_grid lime    8 "$outdir/grid_green.png"     # labels A9..O16
