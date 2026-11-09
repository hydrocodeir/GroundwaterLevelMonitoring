import csv
import pathlib
import sys

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "frontend/assets/js"))
sys.path.insert(0, str(ROOT / "scripts"))
import aquifer3d_compute as compute
import digitize_neyshabur_bedrock as digitize

source = Image.open("C:/Users/psh2610/AppData/Local/Temp/neyshabur_s4_native.png")
rows = list(csv.DictReader((ROOT / "Data/NEYSHABUR_BEDROCK_DEPTH.csv").open(encoding="utf-8")))
pts = [(float(r["lon"]), float(r["lat"]), float(r["bedrock_depth_m"])) for r in rows]
xs = np.arange(10, 1378, 8)
ys = np.arange(10, 1000, 8)
surface = np.array([
    [compute._contour_idw(pts, *digitize.pixel_to_lonlat(float(x), float(y)), 36.0)
     for x in xs]
    for y in ys
])

fig, ax = plt.subplots(figsize=(18, 13))
ax.imshow(source, extent=(0, 1378, 1000, 0))
contours = ax.contour(xs, ys, surface, levels=np.arange(20, 261, 20),
                      colors="#d900d9", linewidths=1.5)
ax.clabel(contours, inline=True, fontsize=8, fmt="%d")
ax.set(xlim=(0, 1378), ylim=(1000, 0), title="Reconstructed depth contours (magenta) over Fig S4 (green)")
fig.savefig(ROOT / ".tmp/map_qa/qa_surface_overlay.png", dpi=130)
plt.close(fig)

for x, y, expected in [(830, 607, 60), (895, 470, 220), (162, 615, 120),
                        (840, 420, 240), (790, 580, 40), (880, 615, 80)]:
    actual = compute._contour_idw(pts, *digitize.pixel_to_lonlat(x, y), 36.0)
    print(f"label x={x} y={y} expected={expected} predicted={actual:.1f} residual={actual-expected:+.1f}")
print(f"grid depth min={surface.min():.1f}, median={np.median(surface):.1f}, max={surface.max():.1f}")
