r"""Compile both paper configurations locally before any Overleaf push.

The canonical Overleaf clone is copied recursively into a scratch directory, so
the clone remains free of build debris.  The review build keeps ``\commtrue``;
``--both`` also builds the submission form after flipping it to ``\commfalse``.

Run from any working directory::

    python build_paper_local.py
    python build_paper_local.py --both
    python build_paper_local.py --open

The exit code is nonzero if any TeX/BibTeX command fails, no PDF is produced, or
LaTeX reports an error or undefined reference.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve()
PAPER = SCRIPT.parent
PROJECT_ROOT = SCRIPT.parents[2]
CLONE = PROJECT_ROOT / "paper-overleaf"
JOB = "paper_infocom"


def _find_tex_tool(name: str) -> Path | None:
    found = shutil.which(name)
    if found:
        return Path(found)
    fallback = (
        Path.home()
        / "AppData"
        / "Local"
        / "Programs"
        / "MiKTeX"
        / "miktex"
        / "bin"
        / "x64"
        / f"{name}.exe"
    )
    return fallback if fallback.is_file() else None


def run(executable: Path, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(executable), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )


def build(
    *, pdflatex: Path, bibtex: Path, commfalse: bool
) -> tuple[dict[str, object] | None, str | None]:
    """Copy the clone, optionally flip comments off, and run the full build."""
    scratch = Path(tempfile.mkdtemp(prefix="paperbuild_"))
    try:
        shutil.copytree(
            CLONE,
            scratch,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".git"),
        )
        tex = scratch / f"{JOB}.tex"
        source = tex.read_text(encoding="utf-8")
        if commfalse:
            updated = source.replace("\n\\commtrue\n", "\n\\commfalse\n", 1)
            if updated == source:
                shutil.rmtree(scratch, ignore_errors=True)
                return None, "could not find the standalone \\commtrue to flip"
            tex.write_text(updated, encoding="utf-8", newline="\n")

        args = [
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            f"{JOB}.tex",
        ]
        runs = [
            run(pdflatex, args, scratch),
            run(bibtex, [JOB], scratch),
            run(pdflatex, args, scratch),
            run(pdflatex, args, scratch),
        ]
        log_path = scratch / f"{JOB}.log"
        log = (
            log_path.read_text(encoding="utf-8", errors="replace")
            if log_path.exists()
            else (runs[0].stdout or "")
        )
        pdf = scratch / f"{JOB}.pdf"
        return {
            "dir": scratch,
            "pdf": pdf if pdf.exists() else None,
            "log": log,
            "return_codes": [result.returncode for result in runs],
            "stdout": (runs[-1].stdout or "")[-3000:],
        }, None
    except Exception:
        shutil.rmtree(scratch, ignore_errors=True)
        raise


def report(result: dict[str, object], label: str) -> bool:
    print("=" * 78)
    print(label)
    print("=" * 78)
    pdf = result["pdf"]
    if pdf is None:
        print("  BUILD FAILED - no pdf produced")
    log = str(result["log"])
    errors = [
        line
        for line in log.splitlines()
        if re.match(r"^.*:\d+: ", line) or line.startswith("! ")
    ]
    undefined = re.findall(
        r"(?:Reference|Citation) ['`]([^'\s]+)' on page \d+ undefined", log
    )
    multiply_defined = re.findall(r"Label ['`]([^'\s]+)' multiply defined", log)
    overfull = len(re.findall(r"Overfull \\hbox", log))
    return_codes = list(result["return_codes"])

    print(f"  command return codes  : {return_codes}")
    print(f"  errors                : {len(errors)}")
    for error in errors[:8]:
        print(f"      {error[:150]}")
    print(
        "  undefined references  : "
        f"{len(set(undefined))} {sorted(set(undefined))[:6] if undefined else ''}"
    )
    print(
        "  multiply-defined      : "
        f"{len(set(multiply_defined))} "
        f"{sorted(set(multiply_defined))[:4] if multiply_defined else ''}"
    )
    print(f"  overfull hboxes       : {overfull}")

    if isinstance(pdf, Path):
        try:
            import fitz

            document = fitz.open(pdf)
            print(f"  pages                 : {len(document)}   ({pdf.stat().st_size:,} bytes)")
            page_text = [page.get_text() for page in document]
            words = [len(text.split()) for text in page_text]
            print(f"  words per page        : {words}")
            near_empty = [index + 1 for index, count in enumerate(words) if count < 120]
            if near_empty:
                print(f"  *** near-empty pages  : {near_empty}")
            # This is a style diagnostic, not a publication-quality comparison.
            # Ethereal is an arXiv technical report, not a documented conference paper.
            word_count = sum(words)
            em_dash_count = " ".join(page_text).count("—")
            rate = 1000 * em_dash_count / word_count if word_count else 0
            flag = "  <-- above 6.0/1000, read it back" if rate > 6.0 else ""
            print(
                f"  em dashes             : {em_dash_count} = "
                f"{rate:.2f} per 1000 words{flag}"
            )
            document.close()
        except ImportError:
            print("  pages                 : (PyMuPDF not available)")

    bad = (
        any(code != 0 for code in return_codes)
        or bool(errors)
        or bool(undefined)
        or pdf is None
    )
    print(f"  VERDICT               : {'CLEAN' if not bad else 'PROBLEMS ABOVE'}\n")
    return bad


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    pdflatex = _find_tex_tool("pdflatex")
    bibtex = _find_tex_tool("bibtex")
    if pdflatex is None or bibtex is None:
        missing = [
            name
            for name, value in (("pdflatex", pdflatex), ("bibtex", bibtex))
            if value is None
        ]
        raise SystemExit(f"required TeX tool(s) not found: {', '.join(missing)}")
    if not (CLONE / ".git").is_dir():
        raise SystemExit(f"canonical Overleaf clone not found: {CLONE}")

    problems = False
    scratch_dirs: list[Path] = []
    review_output = PAPER / "paper_review_local.pdf"
    try:
        review, error = build(pdflatex=pdflatex, bibtex=bibtex, commfalse=False)
        if error or review is None:
            raise SystemExit(error or "review build failed before reporting")
        scratch_dirs.append(review["dir"])
        problems |= report(review, "REVIEW BUILD  (\\commtrue - reviewer comments visible)")
        if isinstance(review["pdf"], Path):
            shutil.copy2(review["pdf"], review_output)
            print(f"  saved -> {review_output.name}\n")

        if "--both" in argv:
            submission, error = build(pdflatex=pdflatex, bibtex=bibtex, commfalse=True)
            if error or submission is None:
                raise SystemExit(error or "submission build failed before reporting")
            scratch_dirs.append(submission["dir"])
            problems |= report(
                submission,
                "SUBMISSION BUILD  (\\commfalse - all comments removed)",
            )
            submission_output = PAPER / "paper_submission_local.pdf"
            if isinstance(submission["pdf"], Path):
                shutil.copy2(submission["pdf"], submission_output)
                print(f"  saved -> {submission_output.name}")

        if "--open" in argv and review_output.exists():
            subprocess.Popen(["cmd", "/c", "start", "", str(review_output)], shell=False)
        return 1 if problems else 0
    finally:
        for directory in scratch_dirs:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
