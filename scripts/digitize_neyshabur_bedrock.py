"""Reproduce approximate Neyshabur bedrock-depth points from Izady et al. Fig. S4.

This is an offline source-asset preparation tool, not an application calculation.
The browser's Pyodide worker consumes the generated CSV on the client.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
from urllib.request import urlopen

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import binary_closing, label
from scipy.spatial import cKDTree


SOURCE_URL = (
    "https://static-content.springer.com/esm/art%3A10.1007%2Fs10040-014-1219-9/"
    "MediaObjects/10040_2014_1219_MOESM1_ESM.pdf"
)
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Data" / "NEYSHABUR_BEDROCK_DEPTH_SOURCE.csv"

# Local contour control positions guided by printed depth labels in native
# figure pixels. Some positions follow the interpreted contour near a label
# rather than the center of its text. They are estimates, not sounding values.
PRINTED_LABELS = [
    (100, 135, 160), (210, 155, 140), (130, 195, 200), (200, 235, 180),
    (355, 290, 180), (280, 365, 100), (370, 395, 120), (270, 475, 80),
    (435, 175, 80), (462, 235, 80), (535, 240, 120), (605, 280, 200),
    (425, 390, 160), (460, 465, 180), (680, 275, 200), (735, 510, 120),
    (840, 420, 240), (895, 470, 220), (970, 515, 200),
    (790, 580, 40), (830, 607, 60), (880, 615, 80),
    (1000, 630, 140), (1020, 670, 100), (1100, 720, 140),
    (162, 615, 120), (265, 725, 80), (570, 805, 140), (735, 900, 180),
    (460, 545, 120), (730, 620, 100), (925, 635, 180),
    (850, 805, 120), (950, 810, 100),
]

# Whole connected segments inspected against the printed map. A number of
# other components merge different contour values in this raster figure, so
# they are deliberately not assigned wholesale (notably IDs 112, 191, 240,
# 326 and 384). Other depth labels below are treated as localized point
# estimates where the line is fragmented or ambiguous.
CURATED_COMPONENTS = {
    154: 160,  # northwest shoulder
    156: 180,  # northwest enclosing 200-m pocket
    159: 200,  # northwest closed pocket
    182: 120,  # northern closed pocket
    203: 200,  # short north-eastern margin
    321: 200,  # eastern margin
    369: 40,   # shallow center near interior boundary
    367: 140,  # eastern center
    451: 100,  # eastern-center local contour
    463: 140,  # southeast small pocket
}

# Linear registration to the project aquifer outline (WGS84 lon/lat -> figure px).
# See Data/NEYSHABUR_BEDROCK_DEPTH.csv.metadata.json for control and limitations.
def lonlat_to_pixel(lon: float, lat: float) -> tuple[float, float]:
    return 55 + 1221 * (lon - 58.277), 122 + 1309 * (36.405 - lat)


def pixel_to_lonlat(x: float, y: float) -> tuple[float, float]:
    return 58.277 + (x - 55) / 1221, 36.405 - (y - 122) / 1309


def read_figure_image(pdf_path: Path | None) -> Image.Image:
    content = pdf_path.read_bytes() if pdf_path else urlopen(SOURCE_URL, timeout=30).read()
    document = pymupdf.open(stream=content, filetype="pdf")
    page = document[4]
    image = document.extract_image(page.get_images(full=True)[0][0])
    return Image.open(io.BytesIO(image["image"])).convert("RGB")


def contour_components(image: Image.Image) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rgb = np.asarray(image)
    # Fig. S4 uses pure lime (#55ff00) for bedrock iso-depths. Include its
    # antialiased pixels; exclude cyan sounding points and blue rivers.
    mask = (
        (rgb[:, :, 0] > 30)
        & (rgb[:, :, 0] < 150)
        & (rgb[:, :, 1] > 180)
        & (rgb[:, :, 2] < 100)
    )
    mask = binary_closing(mask, structure=np.ones((3, 3), dtype=bool))
    components, count = label(mask, structure=np.ones((3, 3), dtype=bool))
    sizes = np.bincount(components.ravel(), minlength=count + 1)
    return mask, components, sizes


def write_debug_image(image: Image.Image, components: np.ndarray, sizes: np.ndarray, path: Path) -> None:
    source = np.asarray(image)
    canvas = np.full_like(source, 255)
    canvas[components > 0] = [0, 175, 0]
    result = Image.fromarray(canvas).resize((image.width * 2, image.height * 2))
    draw = ImageDraw.Draw(result)
    font = ImageFont.truetype("arial.ttf", 20)
    for component_id in np.flatnonzero(sizes >= 100):
        if component_id == 0:
            continue
        ys, xs = np.where(components == component_id)
        # Representative point lies on the line, unlike a bounding-box center.
        k = len(xs) // 2
        draw.text((int(xs[k] * 2), int(ys[k] * 2)), str(component_id), fill=(180, 0, 0), font=font)
    result.save(path)


def provisional_component_depths(components: np.ndarray, sizes: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    anchor_xy = np.array([(x, y) for x, y, _ in PRINTED_LABELS], dtype=float)
    anchor_depth = np.array([depth for _, _, depth in PRINTED_LABELS], dtype=float)
    tree = cKDTree(anchor_xy)
    rows = []
    for component_id in np.flatnonzero(sizes >= 100):
        if component_id == 0:
            continue
        ys, xs = np.where(components == component_id)
        sample = np.arange(0, len(xs), max(1, len(xs) // 50))
        dist, idx = tree.query(np.stack((xs[sample], ys[sample]), axis=1), k=7)
        weights = 1 / np.maximum(dist, 3) ** 2
        values = (weights * anchor_depth[idx]).sum(axis=1) / weights.sum(axis=1)
        rounded = 20 * round(float(np.median(values)) / 20)
        rows.append((int(component_id), int(sizes[component_id]), int(round(np.median(xs))), int(round(np.median(ys))), rounded))
    return rows


def candidate_points(components: np.ndarray) -> list[tuple[float, float, int]]:
    points: list[tuple[float, float, int]] = []
    for component_id, depth in CURATED_COMPONENTS.items():
        ys, xs = np.where(components == component_id)
        occupied: set[tuple[int, int]] = set()
        for x, y in zip(xs, ys):
            cell = (int(x) // 12, int(y) // 12)
            if cell in occupied:
                continue
            occupied.add(cell)
            lon, lat = pixel_to_lonlat(float(x), float(y))
            points.append((lon, lat, depth))
    for x, y, depth in PRINTED_LABELS:
        lon, lat = pixel_to_lonlat(x, y)
        points.append((lon, lat, depth))
    # Source figure labels and line fragments may overlap. Deduplicate after
    # rounding to the CSV precision, but retain different contours close by.
    return sorted({(round(lon, 6), round(lat, 6), depth) for lon, lat, depth in points})


def save_candidate(points: list[tuple[float, float, int]]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(("lon", "lat", "bedrock_depth_m"))
        writer.writerows(points)
    metadata = {
        "source": SOURCE_URL,
        "citation": "Izady et al., Hydrogeology Journal (2015), electronic supplementary material, Fig. S4",
        "source_variable": "bedrock depth below land surface, metres (not bedrock MSL)",
        "source_method": "bedrock iso-depth lines interpreted from 320 sounding and cross-section controls reported by authors",
        "digitization": "approximate figure registration, selected checked green contour fragments, and label-guided local contour controls",
        "georeferencing": "north-up affine approximation to project Neyshabur AQUIFER.geojson feature 33; no graticule printed on Fig. S4",
        "georeferencing_formula": {"x_pixel": "55+1221*(lon-58.277)", "y_pixel": "122+1309*(36.405-lat)"},
        "quality": "approximate research reconstruction; source and project aquifer boundaries differ by several km locally; printed map omits underlying 320 point coordinates; unlabeled contours were not guessed wholesale",
        "known_limitations": [
            "Contour interval is about 20 m; map labels are not measurements at every output point.",
            "Several source raster line components merge neighboring contours, so only selected checked components are traced.",
            "Coverage is sparse away from selected labeled contours; interpolation and absolute storage are scenario estimates.",
            "Do not interpret cyan sounding dots as measured depth values; the source does not print numeric depths at those dots.",
        ],
        "record_count": len(points),
        "depth_min_m": min(depth for _, _, depth in points),
        "depth_max_m": max(depth for _, _, depth in points),
        "label_guided_anchor_count": len(PRINTED_LABELS),
        "curated_component_count": len(CURATED_COMPONENTS),
        "csv_columns": ["lon", "lat", "bedrock_depth_m"],
    }
    OUTPUT.with_suffix(OUTPUT.suffix + ".metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, help="Already downloaded publisher supplement")
    parser.add_argument("--debug-components", type=Path, help="Write labeled green-line image")
    parser.add_argument("--print-provisional", action="store_true", help="Print provisional component values")
    parser.add_argument("--query", nargs=2, type=int, metavar=("X", "Y"), help="Inspect nearby contours")
    args = parser.parse_args()
    image = read_figure_image(args.pdf)
    _, components, sizes = contour_components(image)
    if args.debug_components:
        write_debug_image(image, components, sizes, args.debug_components)
    if args.print_provisional:
        for row in provisional_component_depths(components, sizes):
            print(*row, sep=",")
    if args.query:
        x, y = args.query
        region = components[max(0, y - 40):y + 41, max(0, x - 40):x + 41]
        for component_id in sorted(set(region.ravel())):
            if component_id == 0 or sizes[component_id] < 30:
                continue
            ys, xs = np.where(components == component_id)
            dist2 = (xs - x) ** 2 + (ys - y) ** 2
            k = np.argmin(dist2)
            if dist2[k] <= 40 ** 2:
                print(f"{component_id},{sizes[component_id]},{xs[k]},{ys[k]},{dist2[k] ** .5:.1f}")
    points = candidate_points(components)
    save_candidate(points)
    print(f"Wrote {len(points)} points to {OUTPUT}")
    print(f"Image {image.width}x{image.height}; {int((sizes[1:] >= 100).sum())} components >=100 pixels")


if __name__ == "__main__":
    main()
