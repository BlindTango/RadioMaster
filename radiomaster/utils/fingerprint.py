"""Chromaprint `fpcalc` locator (sidecar pattern, mirrors utils.ffmpeg).

fpcalc is required by AcoustID audio fingerprint lookups. It is not bundled
by default (Chromaprint is a separate, optional download); AcoustID-based
track recognition degrades gracefully to skipped when it is absent.
"""

import os
import shutil

from .paths import resources_dir


def find_fpcalc(override: str | None = None) -> str | None:
    exe = "fpcalc.exe" if os.name == "nt" else "fpcalc"

    if override and os.path.isfile(override):
        return override

    bundled = os.path.join(resources_dir("fpcalc"), exe)
    if os.path.isfile(bundled):
        return bundled

    return shutil.which("fpcalc")
