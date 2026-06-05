"""
Convert .docx to .pdf. Tries in order:
  1. docx2pdf (Word on Windows/Mac, cleanest)
  2. libreoffice --headless (Linux/anywhere with LibreOffice installed)
If both fail, we skip the PDF (the .docx is still produced) and log a warning.
"""
from __future__ import annotations
from pathlib import Path
import logging
import shutil
import subprocess
import sys

LOG = logging.getLogger(__name__)


def docx_to_pdf(docx_path: Path) -> Path | None:
    pdf_path = docx_path.with_suffix(".pdf")

    # Try docx2pdf first (uses MS Word via COM on Win, AppleScript on Mac).
    # On Windows, COM automation requires the calling thread to be initialised
    # as STA (Single-Threaded Apartment). Python's main thread is STA by
    # default, but daemon threads (e.g. the server's pipeline worker) are not,
    # so we call CoInitialize() explicitly before invoking Word and
    # CoUninitialize() after.  Both are no-ops on non-Windows platforms.
    try:
        import pythoncom  # type: ignore  # only present on Windows (pywin32)
        pythoncom.CoInitialize()
        _com_inited = True
    except Exception:
        _com_inited = False

    try:
        from docx2pdf import convert  # type: ignore
        convert(str(docx_path), str(pdf_path))
        if pdf_path.exists():
            return pdf_path
    except Exception as e:
        LOG.warning("docx2pdf failed: %s", e)
    finally:
        if _com_inited:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    # Try libreoffice
    lo = shutil.which("libreoffice") or shutil.which("soffice")
    if lo:
        try:
            subprocess.run(
                [lo, "--headless", "--convert-to", "pdf",
                 "--outdir", str(docx_path.parent), str(docx_path)],
                check=True, capture_output=True, timeout=60,
            )
            if pdf_path.exists():
                return pdf_path
        except Exception as e:
            LOG.debug("libreoffice failed: %s", e)

    LOG.warning("Could not produce PDF for %s — install LibreOffice or MS Word.",
                docx_path.name)
    return None
