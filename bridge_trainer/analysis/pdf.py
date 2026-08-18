"""PDF export for analysis reports via headless Chromium.

The report HTML already carries @media print rules, so the same document
renders correctly on screen, via browser print-to-PDF, and here. Several
browser binaries are tried IN ORDER until one renders successfully — a
name being on PATH does not mean it works (on GitHub's ubuntu runners
`chromium-browser` is a snap stub that exits with an error, while
`google-chrome` works). When nothing renders, export_pdf() returns None
and the caller offers the in-browser print path instead (documented
fallback, DECISIONS.md §2.7).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# real installs first; `chromium-browser` LAST — on Ubuntu it is often a
# snap wrapper that fails headless, and a working binary must win
_CANDIDATES = ("chromium", "google-chrome", "google-chrome-stable",
               "headless_shell", "chromium-browser")


def find_chromiums() -> list[str]:
    """Every plausible Chromium binary, best-first. Existence only — the
    caller must be prepared for any of them to fail at run time."""
    found: list[str] = []
    env_dir = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env_dir:
        for name in _CANDIDATES:
            p = Path(env_dir) / name
            if p.is_file() and os.access(p, os.X_OK):
                found.append(str(p))
        for name in ("chrome", "headless_shell", "chromium"):
            for h in sorted(Path(env_dir).glob(f"**/{name}")):
                if h.is_file() and os.access(h, os.X_OK):
                    found.append(str(h))
    for name in _CANDIDATES:
        p = shutil.which(name)
        if p:
            found.append(p)
    seen: set[str] = set()
    return [p for p in found if not (p in seen or seen.add(p))]


def find_chromium() -> str | None:
    """First candidate, or None — a cheap availability probe for callers
    that only need to decide whether PDF export is worth attempting."""
    cands = find_chromiums()
    return cands[0] if cands else None


def _try_render(chromium: str, html_path: Path, pdf_path: Path,
                timeout_s: float) -> bool:
    with tempfile.TemporaryDirectory() as profile:
        cmd = [
            chromium, "--headless", "--disable-gpu", "--no-sandbox",
            f"--user-data-dir={profile}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True,
                           timeout=timeout_s)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                OSError):
            return False
    return pdf_path.is_file() and pdf_path.stat().st_size > 0


def export_pdf(html_path: str | Path, pdf_path: str | Path,
               timeout_s: float = 60.0) -> Path | None:
    """Render an HTML report file to PDF, trying every available browser
    binary until one succeeds. Returns the path, or None when none can."""
    html_path = Path(html_path).resolve()
    pdf_path = Path(pdf_path).resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    for chromium in find_chromiums():
        if _try_render(chromium, html_path, pdf_path, timeout_s):
            return pdf_path
        pdf_path.unlink(missing_ok=True)   # partial output from a failure
    return None
