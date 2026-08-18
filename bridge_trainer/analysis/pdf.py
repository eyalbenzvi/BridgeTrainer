"""PDF export for analysis reports via headless Chromium.

The report HTML already carries @media print rules, so the same document
renders correctly on screen, via browser print-to-PDF, and here. Chromium
is located from PLAYWRIGHT_BROWSERS_PATH / common binary names; when no
browser is available export_pdf() returns None and the caller offers the
in-browser print path instead (documented fallback, DECISIONS.md §2.7).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_CANDIDATES = ("chromium", "chromium-browser", "google-chrome",
               "google-chrome-stable", "headless_shell")


def find_chromium() -> str | None:
    env_dir = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env_dir:
        for name in _CANDIDATES:
            p = Path(env_dir) / name
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
        for name in ("chrome", "headless_shell", "chromium"):
            hits = sorted(Path(env_dir).glob(f"**/{name}"))
            for h in hits:
                if h.is_file() and os.access(h, os.X_OK):
                    return str(h)
    for name in _CANDIDATES:
        p = shutil.which(name)
        if p:
            return p
    return None


def export_pdf(html_path: str | Path, pdf_path: str | Path,
               timeout_s: float = 60.0) -> Path | None:
    """Render an HTML report file to PDF. Returns the path, or None when no
    Chromium is available or rendering fails."""
    chromium = find_chromium()
    if chromium is None:
        return None
    html_path = Path(html_path).resolve()
    pdf_path = Path(pdf_path).resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
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
            return None
    return pdf_path if pdf_path.is_file() and pdf_path.stat().st_size else None
