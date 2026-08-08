"""Gate the Unit 2A figure-label rebuild against its frozen baseline.

This script is deliberately read-only with respect to the figures.  It compares:

* the before/after artist manifests emitted by ``audit_figure_structure.py``;
* baseline and rebuilt PDFs using PyMuPDF page boxes, vector drawings, and the
  semantic font inventory; and
* baseline and rebuilt PNG dimensions and colour modes.

The artist geometry/data must be byte-for-byte equal as parsed JSON.  Exactly
three rendered-label substitutions are allowed, at their original artist
locations; every other label must remain identical.

Run from the ring-simulator repository root after preserving the old PNGs and
rebuilding the two local figures, but before copying the new PDFs to Overleaf::

    python investigations/rate_model_revalidation_2026_08_06/compare_figure_artifacts.py \
      --baseline-png-dir investigations/rate_model_revalidation_2026_08_06/figure_baseline

The default baseline PDF directory is the sibling ``paper-overleaf`` clone and
the default rebuilt PDF/PNG directory is ``ring-simulator/paper``.  The command
writes concise JSON and Markdown reports and exits nonzero on any gate failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
AUDIT_DIR = Path(__file__).resolve().parent
FIGURES = ("fig_gap_closure", "fig_saturation")

# The path is (figure stem, axes index, Text-artist index).  Pinning the path as
# well as the pair prevents a moved/copied label from being accepted by accident.
APPROVED_LABEL_SUBSTITUTIONS: dict[tuple[str, int, int], tuple[str, str]] = {
    ("fig_gap_closure", 0, 11): (
        "(bound $-$ realised) / realised (%)",
        "(reference $-$ realised) / realised (%)",
    ),
    ("fig_saturation", 0, 44): (
        "optimal-split bound (dashed, fabric colour)",
        "static local-model reference (dashed, fabric colour)",
    ),
    ("fig_saturation", 1, 0): (
        "realised coincide (3.58$\\times$/3.62$\\times$);\n"
        "bounds diverge (3.9$\\times$ vs 6.0$\\times$)",
        "realised coincide (3.58$\\times$/3.62$\\times$);\n"
        "refs diverge (3.9$\\times$ vs 6.0$\\times$)",
    ),
}

PDF_BOX_NAMES = ("rect", "mediabox", "cropbox", "bleedbox", "trimbox", "artbox")
SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value: Any) -> Any:
    """Convert PyMuPDF objects and tuples into deterministic JSON values."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    # Rect, Point, Quad, Matrix, and similar PyMuPDF sequence types.
    try:
        return [canonical(item) for item in value]
    except TypeError:
        return str(value)


def first_difference(left: Any, right: Any, path: str = "$") -> str | None:
    """Return a concise path to the first structural/value difference."""

    if type(left) is not type(right):
        return f"{path}: type {type(left).__name__} != {type(right).__name__}"
    if isinstance(left, dict):
        if left.keys() != right.keys():
            missing = sorted(set(left) - set(right))
            added = sorted(set(right) - set(left))
            return f"{path}: keys differ (before-only={missing}, after-only={added})"
        for key in left:
            difference = first_difference(left[key], right[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: length {len(left)} != {len(right)}"
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            difference = first_difference(left_item, right_item, f"{path}[{index}]")
            if difference:
                return difference
        return None
    if left != right:
        return f"{path}: {left!r} != {right!r}"
    return None


def json_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_artist_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != set(FIGURES):
        raise ValueError(f"{path}: expected exactly {list(FIGURES)}, found {sorted(payload)}")
    for figure in FIGURES:
        fields = set(payload[figure])
        if not {"geometry", "labels"}.issubset(fields) or fields - {
            "geometry",
            "labels",
            "text_bboxes",
        }:
            raise ValueError(f"{path}: malformed manifest entry for {figure}")
    return payload


def flatten_labels(manifest: dict[str, Any]) -> dict[tuple[str, int, int], str]:
    flattened: dict[tuple[str, int, int], str] = {}
    for figure in FIGURES:
        axes = manifest[figure]["labels"]
        if not isinstance(axes, list):
            raise ValueError(f"{figure}.labels is not a list")
        for axes_index, labels in enumerate(axes):
            if not isinstance(labels, list):
                raise ValueError(f"{figure}.labels[{axes_index}] is not a list")
            for text_index, label in enumerate(labels):
                if not isinstance(label, str):
                    raise ValueError(
                        f"{figure}.labels[{axes_index}][{text_index}] is not a string"
                    )
                flattened[(figure, axes_index, text_index)] = label
    return flattened


def compare_text_bboxes(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
    """Require every unchanged label's rendered box to remain identical.

    Width/height (and, for aligned text, one edge) can legitimately change for
    an approved replacement string.  Its artist position and style are already
    pinned in ``geometry.text_styles``; only those three bounding boxes are
    exempted here.
    """

    errors: list[str] = []
    changed_approved: list[dict[str, Any]] = []
    for figure in FIGURES:
        has_before = "text_bboxes" in before[figure]
        has_after = "text_bboxes" in after[figure]
        if has_before != has_after:
            errors.append(f"{figure}: text_bboxes present in only one manifest")
            continue
        if not has_before:
            continue
        left_axes = before[figure]["text_bboxes"]
        right_axes = after[figure]["text_bboxes"]
        if len(left_axes) != len(right_axes):
            errors.append(
                f"{figure}: text-bbox axes length {len(left_axes)} != {len(right_axes)}"
            )
            continue
        for axes_index, (left_boxes, right_boxes) in enumerate(zip(left_axes, right_axes)):
            if len(left_boxes) != len(right_boxes):
                errors.append(
                    f"{figure} axis {axes_index}: text-bbox length "
                    f"{len(left_boxes)} != {len(right_boxes)}"
                )
                continue
            for text_index, (left_box, right_box) in enumerate(zip(left_boxes, right_boxes)):
                location = (figure, axes_index, text_index)
                if left_box == right_box:
                    continue
                if location in APPROVED_LABEL_SUBSTITUTIONS:
                    changed_approved.append(
                        {
                            "figure": figure,
                            "axes": axes_index,
                            "text": text_index,
                            "before": left_box,
                            "after": right_box,
                        }
                    )
                else:
                    errors.append(
                        f"{location}: unapproved rendered text bounding box changed "
                        f"from {left_box!r} to {right_box!r}"
                    )
    return {
        "pass": not errors,
        "approved_changed_boxes": changed_approved,
        "errors": errors,
    }


def compare_artist_manifests(before_path: Path, after_path: Path) -> dict[str, Any]:
    before = load_artist_manifest(before_path)
    after = load_artist_manifest(after_path)

    geometry_results: dict[str, Any] = {}
    geometry_ok = True
    for figure in FIGURES:
        left = before[figure]["geometry"]
        right = after[figure]["geometry"]
        difference = first_difference(left, right)
        passed = difference is None
        geometry_ok &= passed
        geometry_results[figure] = {
            "pass": passed,
            "before_sha256": json_sha256(left),
            "after_sha256": json_sha256(right),
            "first_difference": difference,
        }

    before_labels = flatten_labels(before)
    after_labels = flatten_labels(after)
    observed_changes: list[dict[str, Any]] = []
    label_errors: list[str] = []
    if before_labels.keys() != after_labels.keys():
        removed = sorted(set(before_labels) - set(after_labels))
        added = sorted(set(after_labels) - set(before_labels))
        label_errors.append(f"label artist paths differ: before-only={removed}, after-only={added}")

    for location in sorted(set(before_labels) | set(after_labels)):
        old = before_labels.get(location)
        new = after_labels.get(location)
        if old != new:
            observed_changes.append(
                {
                    "figure": location[0],
                    "axes": location[1],
                    "text": location[2],
                    "before": old,
                    "after": new,
                }
            )

    for location, (expected_before, expected_after) in APPROVED_LABEL_SUBSTITUTIONS.items():
        actual_before = before_labels.get(location)
        actual_after = after_labels.get(location)
        if (actual_before, actual_after) != (expected_before, expected_after):
            label_errors.append(
                f"{location}: expected {expected_before!r} -> {expected_after!r}; "
                f"observed {actual_before!r} -> {actual_after!r}"
            )

    approved_locations = set(APPROVED_LABEL_SUBSTITUTIONS)
    changed_locations = {
        (item["figure"], item["axes"], item["text"]) for item in observed_changes
    }
    unexpected = sorted(changed_locations - approved_locations)
    missing = sorted(approved_locations - changed_locations)
    if unexpected:
        label_errors.append(f"unapproved changed label locations: {unexpected}")
    if missing:
        label_errors.append(f"approved substitutions not observed: {missing}")

    text_bboxes = compare_text_bboxes(before, after)

    return {
        "pass": geometry_ok and not label_errors and text_bboxes["pass"],
        "geometry_data": {"pass": geometry_ok, "figures": geometry_results},
        "rendered_labels": {
            "pass": not label_errors,
            "approved_change_count": len(APPROVED_LABEL_SUBSTITUTIONS),
            "observed_change_count": len(observed_changes),
            "observed_changes": observed_changes,
            "errors": label_errors,
        },
        "rendered_text_bboxes": text_bboxes,
    }


def pdf_font_inventory(page: fitz.Page) -> list[dict[str, Any]]:
    """Return a semantic inventory, ignoring random six-letter subset tags."""

    inventory = []
    for font in page.get_fonts(full=True):
        # PyMuPDF: xref, extension, type, basefont, resource name, encoding,
        # referencer.  Xrefs and subset prefixes are serialization details; the
        # remaining fields identify the rendered font inventory.
        _xref, extension, font_type, basefont, resource, encoding, _referencer = font
        inventory.append(
            {
                "extension": extension,
                "type": font_type,
                "basefont": SUBSET_PREFIX.sub("", basefont),
                "resource": resource,
                "encoding": encoding,
            }
        )
    return sorted(inventory, key=lambda item: json.dumps(item, sort_keys=True))


def pdf_manifest(path: Path) -> dict[str, Any]:
    pages = []
    with fitz.open(path) as document:
        for page in document:
            boxes = {name: canonical(getattr(page, name)) for name in PDF_BOX_NAMES}
            pages.append(
                {
                    "rotation": page.rotation,
                    "boxes": boxes,
                    "drawings": canonical(page.get_drawings()),
                    "fonts": pdf_font_inventory(page),
                }
            )
    return {"page_count": len(pages), "pages": pages}


def compare_pdfs(baseline_dir: Path, rebuilt_dir: Path) -> dict[str, Any]:
    figures: dict[str, Any] = {}
    all_passed = True
    for figure in FIGURES:
        baseline = baseline_dir / f"{figure}.pdf"
        rebuilt = rebuilt_dir / f"{figure}.pdf"
        left = pdf_manifest(baseline)
        right = pdf_manifest(rebuilt)

        left_boxes = [{"rotation": page["rotation"], "boxes": page["boxes"]} for page in left["pages"]]
        right_boxes = [{"rotation": page["rotation"], "boxes": page["boxes"]} for page in right["pages"]]
        left_drawings = [page["drawings"] for page in left["pages"]]
        right_drawings = [page["drawings"] for page in right["pages"]]
        left_fonts = [page["fonts"] for page in left["pages"]]
        right_fonts = [page["fonts"] for page in right["pages"]]

        page_count_equal = left["page_count"] == right["page_count"]
        boxes_difference = first_difference(left_boxes, right_boxes)
        drawings_difference = first_difference(left_drawings, right_drawings)
        fonts_difference = first_difference(left_fonts, right_fonts)
        passed = (
            page_count_equal
            and boxes_difference is None
            and drawings_difference is None
            and fonts_difference is None
        )
        all_passed &= passed
        figures[figure] = {
            "pass": passed,
            "baseline": str(baseline.resolve()),
            "rebuilt": str(rebuilt.resolve()),
            "baseline_sha256": sha256(baseline),
            "rebuilt_sha256": sha256(rebuilt),
            "page_count_equal": page_count_equal,
            "page_boxes_equal": boxes_difference is None,
            "drawings_equal": drawings_difference is None,
            "semantic_fonts_equal": fonts_difference is None,
            "drawing_count_by_page": [len(items) for items in left_drawings],
            "first_box_difference": boxes_difference,
            "first_drawing_difference": drawings_difference,
            "first_font_difference": fonts_difference,
        }
    return {"pass": all_passed, "figures": figures}


def png_properties(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        return {"width": image.width, "height": image.height, "mode": image.mode}


def compare_pngs(baseline_dir: Path, rebuilt_dir: Path) -> dict[str, Any]:
    figures: dict[str, Any] = {}
    all_passed = True
    for figure in FIGURES:
        baseline = baseline_dir / f"{figure}.png"
        rebuilt = rebuilt_dir / f"{figure}.png"
        left = png_properties(baseline)
        right = png_properties(rebuilt)
        passed = left == right
        all_passed &= passed
        figures[figure] = {
            "pass": passed,
            "baseline": str(baseline.resolve()),
            "rebuilt": str(rebuilt.resolve()),
            "baseline_sha256": sha256(baseline),
            "rebuilt_sha256": sha256(rebuilt),
            "baseline_properties": left,
            "rebuilt_properties": right,
        }
    return {"pass": all_passed, "figures": figures}


def markdown_report(report: dict[str, Any]) -> str:
    status = "PASS" if report["pass"] else "FAIL"
    lines = [
        "# Unit 2A figure gate",
        "",
        f"**Status: {status}**",
        "",
        "| Check | Result | Evidence |",
        "|---|---|---|",
    ]
    artists = report["checks"]["artist_manifests"]
    lines.append(
        "| Artist geometry/data | "
        f"{'PASS' if artists['geometry_data']['pass'] else 'FAIL'} | "
        "Exact parsed-JSON equality for both figures |"
    )
    labels = artists["rendered_labels"]
    lines.append(
        "| Rendered labels | "
        f"{'PASS' if labels['pass'] else 'FAIL'} | "
        f"{labels['observed_change_count']} observed; "
        f"{labels['approved_change_count']} exact substitutions approved |"
    )
    text_bboxes = artists["rendered_text_bboxes"]
    lines.append(
        "| Other rendered text boxes | "
        f"{'PASS' if text_bboxes['pass'] else 'FAIL'} | "
        "Unchanged labels retain exact bounding boxes; approved labels exempt |"
    )
    for figure in FIGURES:
        pdf = report["checks"]["pdf_artifacts"]["figures"][figure]
        lines.append(
            f"| `{figure}.pdf` | {'PASS' if pdf['pass'] else 'FAIL'} | "
            f"boxes={pdf['page_boxes_equal']}; drawings={pdf['drawings_equal']}; "
            f"fonts={pdf['semantic_fonts_equal']} |"
        )
        png = report["checks"]["png_artifacts"]["figures"][figure]
        props = png["rebuilt_properties"]
        lines.append(
            f"| `{figure}.png` | {'PASS' if png['pass'] else 'FAIL'} | "
            f"{props['width']}×{props['height']} `{props['mode']}` |"
        )

    if report["errors"]:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {error}" for error in report["errors"])
    else:
        lines.extend(
            [
                "",
                "Only the three approved rendered strings changed; plotted geometry, "
                "data, page boxes, vector drawings, font inventory, and PNG dimensions "
                "are unchanged.",
            ]
        )
    return "\n".join(lines) + "\n"


def collect_errors(checks: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    artists = checks["artist_manifests"]
    for figure, result in artists["geometry_data"]["figures"].items():
        if not result["pass"]:
            errors.append(f"{figure}: artist geometry/data changed: {result['first_difference']}")
    errors.extend(artists["rendered_labels"]["errors"])
    errors.extend(artists["rendered_text_bboxes"]["errors"])

    for figure, result in checks["pdf_artifacts"]["figures"].items():
        if not result["page_count_equal"]:
            errors.append(f"{figure}.pdf: page count changed")
        if not result["page_boxes_equal"]:
            errors.append(f"{figure}.pdf: page boxes changed: {result['first_box_difference']}")
        if not result["drawings_equal"]:
            errors.append(f"{figure}.pdf: drawings changed: {result['first_drawing_difference']}")
        if not result["semantic_fonts_equal"]:
            errors.append(f"{figure}.pdf: semantic font inventory changed: {result['first_font_difference']}")

    for figure, result in checks["png_artifacts"]["figures"].items():
        if not result["pass"]:
            errors.append(
                f"{figure}.png: dimensions/mode changed: "
                f"{result['baseline_properties']} != {result['rebuilt_properties']}"
            )
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--before-manifest",
        type=Path,
        default=AUDIT_DIR / "figure_structure_before.json",
    )
    parser.add_argument(
        "--after-manifest",
        type=Path,
        default=AUDIT_DIR / "figure_structure_after.json",
    )
    parser.add_argument(
        "--baseline-pdf-dir",
        type=Path,
        default=ROOT.parent / "paper-overleaf",
    )
    parser.add_argument("--rebuilt-pdf-dir", type=Path, default=ROOT / "paper")
    parser.add_argument(
        "--baseline-png-dir",
        type=Path,
        default=AUDIT_DIR / "figure_baseline",
    )
    parser.add_argument("--rebuilt-png-dir", type=Path, default=ROOT / "paper")
    parser.add_argument(
        "--json-out",
        type=Path,
        default=AUDIT_DIR / "figure_comparison_report.json",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=AUDIT_DIR / "figure_comparison_report.md",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        checks = {
            "artist_manifests": compare_artist_manifests(
                args.before_manifest, args.after_manifest
            ),
            "pdf_artifacts": compare_pdfs(args.baseline_pdf_dir, args.rebuilt_pdf_dir),
            "png_artifacts": compare_pngs(args.baseline_png_dir, args.rebuilt_png_dir),
        }
        errors = collect_errors(checks)
    except Exception as exc:  # still leave a durable failure report for review
        checks = {}
        errors = [f"gate could not complete: {type(exc).__name__}: {exc}"]

    report = {
        "gate": "unit_2a_figure_label_only",
        "pass": not errors,
        "checks": checks,
        "errors": errors,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    args.markdown_out.write_text(markdown_report(report) if checks else (
        "# Unit 2A figure gate\n\n"
        "**Status: FAIL**\n\n"
        + "\n".join(f"- {error}" for error in errors)
        + "\n"
    ), encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "errors": errors}, ensure_ascii=False))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
