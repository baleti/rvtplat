#!/bin/sh
# copy this package into the vendored locations of the apps (remote-host trees); run after changing rvtplat, then commit there.
# usage: tools/sync_vendor.sh   (needs ssh remote-host)
set -e
D="$(cd "$(dirname "$0")/.." && pwd)"
for t in "~/src/rvt-viewer/rvtballet/_vendor" "~/dwg-viewer/dwgballet/_vendor"; do
  tar c -C "$D" --exclude=__pycache__ rvtplat | ssh remote-host "mkdir -p $t && tar x -C $t"
  echo "synced $t"
done
