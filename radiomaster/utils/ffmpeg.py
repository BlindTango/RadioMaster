"""Bundled/system FFmpeg + FFprobe path resolution.

Lookup order: <app_dir>/radiomaster/resources/ffmpeg/ first (bundled, portable),
then the configured override, then system PATH.
"""

import os
import shutil

from .paths import resources_dir


def _find(name: str, override: str | None) -> str | None:
    if override and os.path.isfile(override):
        return override

    bundled = os.path.join(resources_dir("ffmpeg"), name)
    if os.path.isfile(bundled):
        return bundled

    on_path = shutil.which(name.rsplit(".", 1)[0])
    if on_path:
        return on_path

    return None


def find_ffmpeg(override: str | None = None) -> str | None:
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    return _find(exe, override)


def find_ffprobe(override: str | None = None) -> str | None:
    exe = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    return _find(exe, override)
