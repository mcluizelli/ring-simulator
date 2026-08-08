"""Compare or safely publish the six paper figures to the Overleaf Git clone.

Dry-run comparison performs no network or file writes::

    python overleaf_sync.py

Publishing requires a clean clone attached to an ``origin/*`` upstream, fetches
that upstream, requires ahead/behind ``0/0``, stages exactly the changed figure
allowlist, verifies the resulting commit tree, and only then pushes::

    python overleaf_sync.py --push
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve()
PAPER = SCRIPT.parent
PROJECT_ROOT = SCRIPT.parents[2]
CLONE = PROJECT_ROOT / "paper-overleaf"
FIGURE_STEMS = (
    "fig_split_mechanism",
    "fig_speedup_by_model",
    "fig_saturation",
    "fig_gap_closure",
    "fig_crossk",
    "fig_controller",
)
ALLOWED_PDFS = tuple(f"{stem}.pdf" for stem in FIGURE_STEMS)


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(CLONE), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode:
        raise RuntimeError(
            f"git {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
        )
    return (result.stdout or "").strip()


def _require_complete_sources() -> None:
    missing = [name for name in ALLOWED_PDFS if not (PAPER / name).is_file()]
    if missing:
        raise RuntimeError(f"required local figure(s) missing: {missing}")


def _require_clean_synced_clone() -> str:
    status = git("status", "--porcelain")
    if status:
        raise RuntimeError(f"Overleaf clone is not clean before push:\n{status}")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        raise RuntimeError("Overleaf clone is not on an attached branch")
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if not upstream.startswith("origin/"):
        raise RuntimeError(f"Overleaf upstream must be under origin/: {upstream!r}")
    git("fetch", "--prune", "origin")
    counts = git("rev-list", "--left-right", "--count", f"HEAD...{upstream}").split()
    if counts != ["0", "0"]:
        raise RuntimeError(
            f"Overleaf clone diverged from {upstream}: ahead/behind={'/'.join(counts)}"
        )
    status_after_fetch = git("status", "--porcelain")
    if status_after_fetch:
        raise RuntimeError(
            f"Overleaf clone changed or became dirty during preflight:\n{status_after_fetch}"
        )
    return upstream


def _comparison() -> list[tuple[Path, Path]]:
    print("figure comparison (local build vs what is in the project):")
    todo: list[tuple[Path, Path]] = []
    for name in ALLOWED_PDFS:
        source = PAPER / name
        destination = CLONE / name
        if not destination.exists():
            print(
                f"  {source.stem:<22} not in project        -> "
                f"would add ({source.stat().st_size:,} B)"
            )
            todo.append((source, destination))
        elif filecmp.cmp(source, destination, shallow=False):
            print(f"  {source.stem:<22} identical             ({source.stat().st_size:,} B)")
        else:
            print(
                f"  {source.stem:<22} DIFFERS               -> "
                f"{destination.stat().st_size:,} B becomes {source.stat().st_size:,} B"
            )
            todo.append((source, destination))
    return todo


def _status_names() -> set[str]:
    names: set[str] = set()
    for line in git("status", "--porcelain").splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        names.add(path.replace("\\", "/"))
    return names


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true", help="copy, commit, and push")
    parser.add_argument(
        "--message", default="Update paper figures", help="short commit message for --push"
    )
    args = parser.parse_args(argv)

    if not (CLONE / ".git").is_dir():
        raise SystemExit(f"canonical Overleaf clone not found: {CLONE}")
    _require_complete_sources()
    print(f"clone: {CLONE}")
    print(
        f"branch: {git('rev-parse', '--abbrev-ref', 'HEAD')}   "
        f"head: {git('log', '-1', '--format=%h %s')}\n"
    )
    todo = _comparison()
    if not args.push:
        print(f"\n{len(todo)} file(s) would change. Re-run with --push to apply.")
        return 0
    if not todo:
        print("\nnothing to do.")
        return 0

    upstream = _require_clean_synced_clone()
    expected_names = {destination.name for _, destination in todo}
    if not expected_names <= set(ALLOWED_PDFS):
        raise RuntimeError(f"internal allowlist violation: {sorted(expected_names)}")

    for source, destination in todo:
        shutil.copy2(source, destination)
        if not filecmp.cmp(source, destination, shallow=False):
            raise RuntimeError(f"post-copy byte verification failed: {destination}")
        print(f"  copied {source.name}")

    git("add", "--", *sorted(expected_names))
    staged_names = set(git("diff", "--cached", "--name-only").splitlines())
    status_names = _status_names()
    if staged_names != expected_names or status_names != expected_names:
        raise RuntimeError(
            "unexpected Overleaf staging set: "
            f"expected={sorted(expected_names)}, staged={sorted(staged_names)}, "
            f"status={sorted(status_names)}"
        )

    git("commit", "-m", args.message)
    committed_names = set(
        git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
    )
    if committed_names != expected_names:
        raise RuntimeError(
            f"unexpected files in Overleaf commit: {sorted(committed_names)}"
        )
    print(git("log", "-1", "--format=%h %s"))
    output = git("push", "origin", f"HEAD:{upstream.removeprefix('origin/')}")
    print(f"\npushed.\n{output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
