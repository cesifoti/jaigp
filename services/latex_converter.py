"""LaTeX source -> HTML conversion via LaTeXML (the arXiv HTML pipeline).

When an author optionally uploads their LaTeX source (.tex or .zip with figures),
this produces a higher-fidelity reading view than any PDF-derived conversion:
real MathML math, correct structure, native tables.

Artifacts follow the existing naming convention: the generated HTML overwrites
{base_path}.html and its graphics land in {base_path}_images/ so the existing
/paper/{id}/html and /paper/{id}/figures/ routes serve them unchanged.
"""
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

LATEXML_TIMEOUT = 600  # seconds; complex papers can be slow

_ASSET_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg")


def source_path_for(base_path: str) -> str | None:
    """Return the stored LaTeX source archive/file for a paper version, if any."""
    for ext in ("-source.zip", "-source.tex"):
        candidate = f"{base_path}{ext}"
        if os.path.exists(candidate):
            return candidate
    return None


def _find_main_tex(root: Path) -> Path | None:
    """Locate the main .tex file (contains \\documentclass) in an unpacked source tree."""
    candidates = []
    for tex in root.rglob("*.tex"):
        try:
            head = tex.read_text(errors="ignore")[:5000]
        except OSError:
            continue
        if "\\documentclass" in head:
            candidates.append(tex)
    if not candidates:
        return None
    # Prefer the shallowest, then conventional names
    candidates.sort(key=lambda p: (len(p.parts), p.name not in ("main.tex", "paper.tex", "ms.tex")))
    return candidates[0]


def convert_latex_source(source_path: str, base_path: str) -> bool:
    """Convert LaTeX source to HTML with latexmlc. Blocking; run in a thread.

    Returns True on success (artifacts written), raises on failure.
    """
    pdf_basename = os.path.basename(base_path)
    image_dir = f"{base_path}_images"
    os.makedirs(image_dir, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="latexml-") as tmp:
        tmp_path = Path(tmp)
        src_dir = tmp_path / "src"
        out_dir = tmp_path / "out"
        src_dir.mkdir()
        out_dir.mkdir()

        if source_path.endswith(".zip"):
            with zipfile.ZipFile(source_path) as zf:
                # Guard against zip-slip: only extract members that resolve inside src_dir
                for member in zf.namelist():
                    target = (src_dir / member).resolve()
                    if not str(target).startswith(str(src_dir.resolve())):
                        raise ValueError(f"Unsafe path in source archive: {member}")
                zf.extractall(src_dir)
            main_tex = _find_main_tex(src_dir)
            if not main_tex:
                raise ValueError("No .tex file with \\documentclass found in archive")
        else:
            main_tex = src_dir / "main.tex"
            shutil.copy(source_path, main_tex)

        dest = out_dir / "index.html"
        result = subprocess.run(
            [
                "latexmlc",
                str(main_tex),
                f"--dest={dest}",
                "--format=html5",
                "--nodefaultresources",  # no local css/js copies; our templates style it
                "--timeout=300",
                "--quiet",
            ],
            cwd=main_tex.parent,
            capture_output=True,
            text=True,
            timeout=LATEXML_TIMEOUT,
        )
        if not dest.exists():
            tail = (result.stderr or result.stdout or "")[-2000:]
            raise RuntimeError(f"latexmlc produced no output (rc={result.returncode}): {tail}")

        html = dest.read_text(encoding="utf-8", errors="replace")

        # Move generated/copied graphics next to the paper and rewrite references
        for asset in sorted(out_dir.rglob("*")):
            if asset.is_file() and asset.suffix.lower() in _ASSET_EXTS:
                rel = asset.relative_to(out_dir).as_posix()
                flat = rel.replace("/", "_")
                shutil.copy(asset, os.path.join(image_dir, flat))
                html = html.replace(f'src="{rel}"', f'src="{pdf_basename}_images/{flat}"')

        with open(f"{base_path}.html", "w", encoding="utf-8") as f:
            f.write(html)

    print(f"✓ LaTeXML-generated HTML: {base_path}.html")
    return True
