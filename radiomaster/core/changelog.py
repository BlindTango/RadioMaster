"""Static changelog shown in the Help > What's New / Release Notes dialog.

Keep this in sync with the notes attached to each GitHub release — update it
alongside radiomaster/__init__.py's __version__ and installer/radiomaster.iss
on every version bump.
"""

from __future__ import annotations

CHANGELOG: dict[str, list[str]] = {
    "1.9.5": [
        "New-install defaults tuned for typical use: volume 40%, pan centred, minimum "
        "kept recording length 31 seconds, auto-play the last station on startup, fade "
        "audio in/out when switching stations (500ms), and advertisement-break detection "
        "all now on by default.",
        "All default Global Hotkeys switched to Shift+Alt+ combinations, and every "
        "hotkey-bindable action (including ones added in 1.9.3, like Podcast Rate Up/ "
        "Down and Open Settings) now gets a default binding automatically, even for "
        "existing installs, so they actually show up in the Hotkeys list instead of "
        "staying invisible until manually added.",
        "Added Pan Left/Pan Right to the list of actions Global Hotkeys can control.",
    ],
    "1.9.4": [
        "Fixed dialogs opening with focus on the OK/Close button instead of the first "
        "real field — Effects, Help, Hotkeys (both the list and the add/edit form), "
        "Recording Scheduler, Settings, Update Available, and What's New now all put "
        "keyboard focus where you'd actually expect it as soon as they open.",
        "Added right-click / context menus (also reachable via the Applications key or "
        "Shift+F10) to every actionable list in the app: the station browser (Play/"
        "Pause, Record, Save to Favourites), Favourites (Play, Remove, Move Up/Down), "
        "Active Recordings (Stop Selected Recording), the Recording Scheduler (Enable/"
        "Disable, Delete), Global Hotkeys (Add, Edit, Remove), and Podcasts (Subscribe, "
        "Unsubscribe, Play Episode).",
    ],
    "1.9.3": [
        "Fixed a regression where a failed stream connection always reported "
        "\"BASS_StreamCreateURL failed (err=0)\" regardless of the actual cause, "
        "making it impossible to tell what went wrong.",
        "Added a Connection retry attempts setting: on a slow or flaky connection, "
        "RadioMaster now retries opening a station or podcast stream a configurable "
        "number of times before giving up, instead of failing on the first attempt.",
        "Global Hotkeys can now also be bound to Podcast Rate Up/Down, Open Recording "
        "Folder, Open Podcast Folder, Open Settings, Open Recording Scheduler, and "
        "Open Help, in addition to the existing Play/Pause, Stop, Record, and Volume "
        "actions.",
        "Updated the Help Contents to document the new connection retry setting and "
        "the expanded list of global hotkey actions.",
    ],
    "1.9.2": [
        "Radio station search is now much faster — the local station catalog is indexed for "
        "instant substring search and is now checked before falling back to a live lookup, "
        "instead of always waiting on a network round-trip.",
    ],
    "1.9.1": [
        "Fixed podcast episodes cutting off their last few seconds and jumping straight "
        "to the next episode — playback now waits for all already-decoded audio to "
        "finish playing before treating an episode as finished.",
    ],
    "1.9.0": [
        "Redesigned the Global Hotkeys settings dialog: it's now a list you can add to, "
        "edit, and remove from, instead of one fixed text box per action — and each "
        "action can now have more than one hotkey bound to it.",
        "Added support for binding multimedia/keyboard media keys (Play/Pause, Stop, "
        "Next/Previous Track, Volume Up/Down, Mute) as global hotkeys, on their own or "
        "combined with Ctrl/Alt/Shift/Win.",
        "Hotkey changes made in Settings now take effect immediately, without needing a "
        "separate Apply click.",
    ],
    "1.8.2": [
        "Fixed recorded tracks sometimes staying stuck under their temporary filename "
        "instead of being renamed to \"Artist - Title\" — the rename now retries briefly "
        "if Windows still has the just-finished file handle open.",
        "Fixed the Radio tab's status bar announcing itself to screen readers roughly "
        "once a second (drowning out the \"Likely advertisement\" flag and anything else "
        "useful) — it now only announces when the spoken text actually changes.",
    ],
    "1.8.1": [
        "Fixed a UI freeze when switching radio stations, caused by the BASS engine's "
        "network connect happening on the UI thread; it now connects in the background.",
        "Fixed the podcast Rate slider taking several seconds to audibly apply — it now "
        "drops the already-buffered old-rate audio instead of waiting for it to drain.",
        "Fixed the Play/Pause button showing the wrong label after switching between the "
        "Radio and Podcasts tabs while something was already playing.",
    ],
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
