"""Checks GitHub Releases for a newer RadioMaster build and downloads the installer."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Callable, Optional

import requests

log = logging.getLogger(__name__)

GITHUB_REPO = "BlindTango/RadioMaster"
_USER_AGENT = "RadioMaster-Updater"


class UpdateCheckError(RuntimeError):
    pass


@dataclass
class UpdateInfo:
    version: str
    notes: str
    html_url: str
    download_url: Optional[str]
    asset_name: Optional[str]


def parse_version(text: str) -> tuple:
    text = text.strip().lstrip("vV")
    parts = re.findall(r"\d+", text)
    return tuple(int(p) for p in parts) or (0,)


def is_newer(remote_version: str, local_version: str) -> bool:
    return parse_version(remote_version) > parse_version(local_version)


class UpdateChecker:
    def __init__(self, repo: str = GITHUB_REPO, proxies: Optional[dict] = None):
        self.repo = repo
        self.proxies = proxies

    def check(self, current_version: str, timeout: float = 10.0) -> Optional[UpdateInfo]:
        url = f"https://api.github.com/repos/{self.repo}/releases/latest"
        try:
            resp = requests.get(
                url, timeout=timeout, proxies=self.proxies,
                headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise UpdateCheckError(f"Could not check for updates: {exc}") from exc

        tag = data.get("tag_name", "")
        if not tag or not is_newer(tag, current_version):
            return None

        download_url = None
        asset_name = None
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.lower().endswith(".exe"):
                download_url = asset.get("browser_download_url")
                asset_name = name
                break

        return UpdateInfo(
            version=tag.lstrip("vV"),
            notes=data.get("body", "") or "",
            html_url=data.get("html_url", f"https://github.com/{self.repo}/releases"),
            download_url=download_url,
            asset_name=asset_name,
        )

    def download_installer(
        self, info: UpdateInfo, dest_path: str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        if not info.download_url:
            raise UpdateCheckError("This release has no downloadable installer asset.")
        try:
            resp = requests.get(info.download_url, timeout=30, proxies=self.proxies, stream=True)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise UpdateCheckError(f"Could not download the update: {exc}") from exc

        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        tmp_path = dest_path + ".part"
        try:
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=262144):
                    if cancel_check and cancel_check():
                        raise UpdateCheckError("Download cancelled.")
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            progress_cb(downloaded, total)
            os.replace(tmp_path, dest_path)
        except OSError as exc:
            raise UpdateCheckError(f"Could not save the downloaded update: {exc}") from exc
        finally:
            if os.path.exists(tmp_path) and not os.path.exists(dest_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
