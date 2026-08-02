"""Static changelog shown in the Help > What's New / Release Notes dialog.

Keep this in sync with the notes attached to each GitHub release — update it
alongside radiomaster/__init__.py's __version__ and installer/radiomaster.iss
on every version bump.
"""

from __future__ import annotations

CHANGELOG: dict[str, list[str]] = {
    "1.8.0": [
        "Added an in-app updater: Help > Check for Updates... checks GitHub for a "
        "newer release, shows its release notes, and can download and launch the "
        "installer for you. Also checks silently once at startup (can be turned off "
        "in Settings).",
        "Added Help > What's New..., which shows the changelog for every version and "
        "pops up automatically the first time you start RadioMaster after an update.",
        "Rewrote Help Contents from scratch to match the current menu-based interface "
        "(Effects/Tools/Help menus, Podcasts tab, file menu shortcuts, updater).",
        "Added a Lyrics panel to the Radio tab: automatically looks up and displays "
        "the currently playing track's lyrics, cleanly formatted with original verse/"
        "chorus spacing preserved.",
    ],
    "1.7.1": [
        "Removed the in-tab EffectsBox widget from the Radio tab; audio effects are "
        "now controlled exclusively via the Effects menu (toggle, presets, settings).",
        "Added File > Open Recording Folder and File > Open Podcast Folder shortcuts.",
    ],
    "1.7.0": [
        "Migrated the audio engine to BASS (bass.dll / bass_fx.dll / bassmix.dll), "
        "replacing the previous ffmpeg-filter-based effects pipeline.",
        "Reorganized the main menu into Effects and Tools menus, replacing the old "
        "Effects/Settings/Scheduler tabs.",
        "Added podcast OPML import/export, plus the ability to add a feed by URL "
        "directly (bypassing directory search).",
    ],
    "1.6.3": [
        "Fixed audio crackling caused by int16 overflow wraparound.",
    ],
}

# Newest-first, taken from CHANGELOG's insertion order rather than a sorted()
# call on the version strings — lexicographic sort would put "1.7.10" before
# "1.7.9", which is wrong.
VERSIONS_NEWEST_FIRST: list[str] = list(CHANGELOG.keys())


def notes_for(version: str) -> list[str]:
    return CHANGELOG.get(version, [])
