"""Plot an aligned lap comparison CSV (from lap_compare.py) against lap distance.

    python lap_plots.py data\\comparisons\\<comparison-file>.csv

Writes four PNGs (speed, throttle, brake, time delta) plus one combined dashboard PNG
to data/plots/. Delta convention matches lap_compare.py: positive = comparison slower.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # render to files only; no window needed
import matplotlib.pyplot as plt  # noqa: E402

from lap_compare import OUT_COLUMNS  # noqa: E402

OUT_DIR = Path("data/plots")

REF_COLOR = "#0072B2"
CMP_COLOR = "#E69F00"
SLOWER_COLOR = "#D55E00"
FASTER_COLOR = "#009E73"

_LAP_RE = re.compile(r"lap(?P<lap>\d+)_(?:(?P<m>\d+)m(?P<s>\d+\.\d+)s|unknown)")


class PlotError(Exception):
    """The comparison CSV cannot be plotted."""


def load_comparison(path):
    """Read an aligned comparison CSV into {column: [floats]}. Raises PlotError."""
    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            missing = [c for c in OUT_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise PlotError(f"{path}: not an aligned comparison CSV, missing columns {missing}")
            data = {c: [] for c in OUT_COLUMNS}
            for row in reader:
                for c in OUT_COLUMNS:
                    data[c].append(float(row[c]))
    except OSError as e:
        raise PlotError(f"cannot read {path}: {e}") from e
    except (ValueError, TypeError) as e:  # TypeError: short row gives None
        raise PlotError(f"{path}: bad or missing value in CSV ({e})") from e
    if len(data["distance_m"]) < 2:
        raise PlotError(f"{path}: needs at least 2 rows to plot")
    return data


def lap_info(path):
    """Lap labels and times parsed from '<ref>__vs__<cmp>.csv'; unknown parts are None."""
    ref_part, _, cmp_part = Path(path).stem.partition("__vs__")
    info = []
    for part in (ref_part, cmp_part):
        m = _LAP_RE.search(part)
        label = f"lap {int(m['lap'])}" if m else part or "lap"
        time_ms = round((int(m["m"]) * 60 + float(m["s"])) * 1000) if m and m["m"] else None
        info.append((label, time_ms))
    return info


def _fmt_time(ms):
    minutes, rest = divmod(ms, 60000)
    return f"{int(minutes)}:{rest / 1000:06.3f}"


def _legend_labels(path):
    (ref_label, ref_ms), (cmp_label, cmp_ms) = lap_info(path)
    ref = f"Reference ({ref_label}" + (f", {_fmt_time(ref_ms)})" if ref_ms else ")")
    cmp_ = f"Comparison ({cmp_label}" + (f", {_fmt_time(cmp_ms)})" if cmp_ms else ")")
    return ref, cmp_


def summary_text(data, path):
    """One line with both lap times and the total difference (falls back to end-of-overlap)."""
    (_, ref_ms), (_, cmp_ms) = lap_info(path)
    ref_label, cmp_label = _legend_labels(path)
    if ref_ms and cmp_ms:
        diff = f"Lap-time difference: {(cmp_ms - ref_ms) / 1000:+.3f} s"
    else:
        diff = f"Delta at {data['distance_m'][-1]:.0f} m: {data['delta_ms'][-1] / 1000:+.3f} s"
    return f"{ref_label}   |   {cmp_label}   |   {diff} (+ = comparison slower)"


def _style(ax, title, ylabel):
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.set_xlabel("Lap distance (m)")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    ax.margins(x=0.01)


def _overlay(ax, data, labels, ref_key, cmp_key, title, ylabel, scale=1.0):
    x = data["distance_m"]
    ax.plot(x, [v * scale for v in data[ref_key]], color=REF_COLOR, lw=1.6, label=labels[0])
    ax.plot(x, [v * scale for v in data[cmp_key]], color=CMP_COLOR, lw=1.6, label=labels[1])
    _style(ax, title, ylabel)
    ax.legend(loc="lower right", fontsize=9)


def draw_speed(ax, data, labels):
    _overlay(ax, data, labels, "ref_speed_kmh", "cmp_speed_kmh", "Speed vs distance", "Speed (km/h)")


def draw_throttle(ax, data, labels):
    _overlay(ax, data, labels, "ref_throttle", "cmp_throttle", "Throttle vs distance",
             "Throttle (%)", scale=100)
    ax.set_ylim(-3, 103)


def draw_brake(ax, data, labels):
    _overlay(ax, data, labels, "ref_brake", "cmp_brake", "Brake vs distance", "Brake (%)", scale=100)
    ax.set_ylim(-3, 103)


def draw_delta(ax, data, labels):
    x = data["distance_m"]
    delta = [d / 1000 for d in data["delta_ms"]]
    ax.fill_between(x, delta, 0, where=[d > 0 for d in delta], interpolate=True,
                    color=SLOWER_COLOR, alpha=0.35, label="Comparison slower (+)")
    ax.fill_between(x, delta, 0, where=[d < 0 for d in delta], interpolate=True,
                    color=FASTER_COLOR, alpha=0.35, label="Comparison faster (-)")
    ax.plot(x, delta, color="#222222", lw=1.4)
    ax.axhline(0, color="black", lw=1.5, label="Zero (equal to reference)")
    _style(ax, "Time delta vs distance", "Delta (s)  [+ = comparison slower]")
    ax.legend(loc="best", fontsize=9)


PLOTS = {
    "speed": draw_speed,
    "throttle": draw_throttle,
    "brake": draw_brake,
    "delta": draw_delta,
}


def make_plots(csv_path, out_dir=OUT_DIR):
    """Create the four plots and the dashboard; returns the list of written PNG paths."""
    data = load_comparison(csv_path)
    labels = _legend_labels(csv_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(csv_path).stem
    written = []

    for name, draw in PLOTS.items():
        fig, ax = plt.subplots(figsize=(11, 5))
        draw(ax, data, labels)
        fig.suptitle(summary_text(data, csv_path), fontsize=9)
        fig.tight_layout(rect=(0, 0, 1, 0.95))
        path = out_dir / f"{stem}_{name}.png"
        fig.savefig(path, dpi=130)
        plt.close(fig)
        written.append(path)

    fig, axes = plt.subplots(2, 2, figsize=(17, 10))
    for ax, draw in zip(axes.flat, PLOTS.values()):
        draw(ax, data, labels)
    fig.suptitle(summary_text(data, csv_path), fontsize=12, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    path = out_dir / f"{stem}_dashboard.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    written.append(path)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description="Plot an aligned lap comparison CSV.")
    ap.add_argument("comparison_csv", help="CSV from lap_compare.py (in data/comparisons/)")
    ap.add_argument("--out-dir", default=str(OUT_DIR), help="where to save PNGs")
    args = ap.parse_args(argv)
    try:
        written = make_plots(args.comparison_csv, args.out_dir)
    except PlotError as e:
        print(f"Error: {e}")
        return 1
    print("Saved plots:")
    for p in written:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
