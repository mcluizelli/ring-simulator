"""Emit a deterministic structure manifest for the two rate-model figures.

The paper figure builder is imported, but ``Figure.savefig`` is intercepted, so
this audit writes no PDF or PNG.  Geometry/data and text strings are emitted in
separate JSON fields: a before/after comparison can therefore prove that plotted
artists are identical while naming the exact strings that changed.

Run from the ring-simulator repository root:

    python investigations/rate_model_revalidation_2026_08_06/audit_figure_structure.py
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib.figure
import matplotlib.text
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "paper" / "build_ieee_eval_figs.py"


def scalar(value: Any) -> Any:
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if math.isnan(number):
            return "nan"
        if math.isinf(number):
            return "inf" if number > 0 else "-inf"
        return round(number, 14)
    if isinstance(value, (str, bool)) or value is None:
        return value
    return str(value)


def vector(values: Any) -> list[Any]:
    array = np.asarray(values, dtype=object).reshape(-1)
    return [scalar(value) for value in array.tolist()]


def nested(values: Any) -> Any:
    if isinstance(values, np.ndarray):
        return nested(values.tolist())
    if isinstance(values, (list, tuple)):
        return [nested(value) for value in values]
    return scalar(values)


def color(value: Any) -> Any:
    return nested(value) if isinstance(value, (list, tuple, np.ndarray)) else scalar(value)


def transform_kind(transform: Any, ax: Any) -> str:
    if transform is ax.transData:
        return "data"
    if transform is ax.transAxes:
        return "axes"
    if transform is ax.figure.transFigure:
        return "figure"
    return type(transform).__name__


def line_manifest(line: Any) -> dict[str, Any]:
    path = line.get_path()
    return {
        "x": vector(line.get_xdata(orig=False)),
        "y": vector(line.get_ydata(orig=False)),
        "linestyle": scalar(line.get_linestyle()),
        "linewidth": scalar(line.get_linewidth()),
        "marker": scalar(line.get_marker()),
        "markersize": scalar(line.get_markersize()),
        "color": color(line.get_color()),
        "markerfacecolor": color(line.get_markerfacecolor()),
        "markeredgecolor": color(line.get_markeredgecolor()),
        "markeredgewidth": scalar(line.get_markeredgewidth()),
        "alpha": scalar(line.get_alpha()),
        "zorder": scalar(line.get_zorder()),
        "drawstyle": scalar(line.get_drawstyle()),
        "display_vertices": nested(line.get_transform().transform(path.vertices)),
    }


def patch_manifest(patch: Any) -> dict[str, Any]:
    item = {
        "type": type(patch).__name__,
        "facecolor": color(patch.get_facecolor()),
        "edgecolor": color(patch.get_edgecolor()),
        "linewidth": scalar(patch.get_linewidth()),
        "linestyle": scalar(patch.get_linestyle()),
        "alpha": scalar(patch.get_alpha()),
        "zorder": scalar(patch.get_zorder()),
    }
    for name in ("get_x", "get_y", "get_width", "get_height", "get_angle"):
        if hasattr(patch, name):
            item[name.removeprefix("get_")] = scalar(getattr(patch, name)())
    if hasattr(patch, "get_path"):
        item["path_vertices"] = nested(patch.get_path().vertices)
        item["path_codes"] = nested(patch.get_path().codes)
        item["display_vertices"] = nested(
            patch.get_transform().transform(patch.get_path().vertices)
        )
    return item


def collection_manifest(collection: Any) -> dict[str, Any]:
    item = {
        "type": type(collection).__name__,
        "offsets": nested(collection.get_offsets()) if hasattr(collection, "get_offsets") else [],
        "array": nested(collection.get_array()) if collection.get_array() is not None else None,
        "linewidths": nested(collection.get_linewidths()),
        "linestyles": nested(collection.get_linestyles()),
        "facecolors": nested(collection.get_facecolors()),
        "edgecolors": nested(collection.get_edgecolors()),
        "alpha": scalar(collection.get_alpha()),
        "zorder": scalar(collection.get_zorder()),
    }
    if hasattr(collection, "get_segments"):
        item["segments"] = nested(collection.get_segments())
    if hasattr(collection, "get_paths"):
        item["paths"] = [
            {"vertices": nested(path.vertices), "codes": nested(path.codes)}
            for path in collection.get_paths()
        ]
    return item


def text_style(text: Any, ax: Any) -> dict[str, Any]:
    item = {
        "position": nested(text.get_position()),
        "transform": transform_kind(text.get_transform(), ax),
        "fontsize": scalar(text.get_fontsize()),
        "fontfamily": nested(text.get_fontfamily()),
        "fontstyle": scalar(text.get_fontstyle()),
        "fontweight": scalar(text.get_fontweight()),
        "rotation": scalar(text.get_rotation()),
        "horizontalalignment": scalar(text.get_horizontalalignment()),
        "verticalalignment": scalar(text.get_verticalalignment()),
        "color": color(text.get_color()),
        "alpha": scalar(text.get_alpha()),
        "zorder": scalar(text.get_zorder()),
        "visible": bool(text.get_visible()),
    }
    if isinstance(text, matplotlib.text.Annotation):
        item["xy"] = nested(text.xy)
        item["xycoords"] = scalar(text.xycoords)
        item["anncoords"] = scalar(text.anncoords)
    return item


def figure_manifest(fig: Any) -> dict[str, Any]:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    geometry = {
        "size_inches": vector(fig.get_size_inches()),
        "dpi": scalar(fig.dpi),
        "axes": [],
    }
    labels = []
    text_bboxes = []
    for index, ax in enumerate(fig.axes):
        texts = ax.findobj(match=lambda artist: isinstance(artist, matplotlib.text.Text))
        arrows = [
            text.arrow_patch
            for text in texts
            if isinstance(text, matplotlib.text.Annotation) and text.arrow_patch is not None
        ]
        geometry["axes"].append(
            {
                "index": index,
                "position": nested(ax.get_position().bounds),
                "xlim": nested(ax.get_xlim()),
                "ylim": nested(ax.get_ylim()),
                "xscale": ax.get_xscale(),
                "yscale": ax.get_yscale(),
                "xticks": nested(ax.get_xticks()),
                "yticks": nested(ax.get_yticks()),
                "lines": [line_manifest(line) for line in ax.lines],
                "xgridlines": [line_manifest(line) for line in ax.get_xgridlines()],
                "ygridlines": [line_manifest(line) for line in ax.get_ygridlines()],
                "patches": [patch_manifest(patch) for patch in ax.patches],
                "annotation_arrows": [patch_manifest(patch) for patch in arrows],
                "collections": [collection_manifest(item) for item in ax.collections],
                "spines": {
                    name: patch_manifest(spine) for name, spine in sorted(ax.spines.items())
                },
                "text_styles": [text_style(text, ax) for text in texts],
            }
        )
        labels.append([text.get_text() for text in texts])
        text_bboxes.append([nested(text.get_window_extent(renderer).bounds) for text in texts])
    return {"geometry": geometry, "labels": labels, "text_bboxes": text_bboxes}


def load_builder() -> Any:
    spec = importlib.util.spec_from_file_location("rate_model_figure_builder", BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {BUILDER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    captured: dict[str, Any] = {}
    original_savefig = matplotlib.figure.Figure.savefig

    def intercept(fig: Any, filename: Any, *args: Any, **kwargs: Any) -> None:
        path = Path(str(filename))
        if path.suffix.lower() == ".pdf":
            captured[path.stem] = figure_manifest(fig)

    module = load_builder()
    matplotlib.figure.Figure.savefig = intercept
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            module.gap_closure()
            module.saturation()
    finally:
        matplotlib.figure.Figure.savefig = original_savefig

    expected = {"fig_gap_closure", "fig_saturation"}
    if set(captured) != expected:
        raise RuntimeError(f"captured {sorted(captured)}, expected {sorted(expected)}")
    payload = json.dumps(captured, indent=2, sort_keys=True) + "\n"
    if len(sys.argv) == 2:
        Path(sys.argv[1]).write_text(payload, encoding="utf-8")
    elif len(sys.argv) == 1:
        print(payload, end="")
    else:
        raise SystemExit("usage: audit_figure_structure.py [output.json]")


if __name__ == "__main__":
    main()
