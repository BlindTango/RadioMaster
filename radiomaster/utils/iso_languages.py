"""Maps a station's raw Radio Browser language data to canonical ISO 639
language names, so "By Language" browsing groups by a fixed, standard set of
languages instead of by whatever free-text string a station happened to be
tagged with.

Radio Browser stations carry two related but independently-unreliable
fields: `language` (free-text names, e.g. "russian,ukrainian") and
`languagecodes` (ISO 639-1 codes, e.g. "ru,uk") — either can be empty even
when the other has data (confirmed: many stations have a language name with
no corresponding code). A station tagged with N languages must show up under
all N canonical buckets, not as its own single combined group — that's what
the station_languages junction table (mirroring station_genres) is for.
"""

from __future__ import annotations

import re
from typing import Optional

import pycountry

_BY_CODE: dict[str, str] = {}
_BY_NAME: dict[str, str] = {}

# Radio Browser's `language` field is free text with no enforced format —
# most stations comma-separate multiple languages ("russian,ukrainian"), but
# some tag a pair as a single fragment with no comma at all
# ("english and spanish"). Splitting only on comma left that whole fragment
# to fail a single pycountry lookup and get dropped silently. This is tried
# ONLY after the whole fragment already failed as one language (see
# _resolve_segment) — so real multi-word ISO names that happen to contain
# "and" as a substring, e.g. "Trinidad and Tobago Sign Language", still
# resolve correctly as themselves instead of being torn apart.
_SECONDARY_SPLIT_RE = re.compile(r"[/;|&]+|\band\b", re.IGNORECASE)


def _build_index() -> None:
    for lang in pycountry.languages:
        canonical = getattr(lang, "name", None)
        if not canonical:
            continue
        alpha_2 = getattr(lang, "alpha_2", None)
        if alpha_2:
            _BY_CODE[alpha_2.lower()] = canonical
        _BY_NAME[canonical.lower()] = canonical
        common = getattr(lang, "common_name", None)
        if common:
            _BY_NAME[common.lower()] = canonical


_build_index()

# ISO 639-3's canonical .name occasionally carries a technical qualifier that
# distinguishes it from a historical/related entry (e.g. "Modern Greek
# (1453-)" vs. Ancient Greek) — correct, but odd-looking in a station browse
# list. Only overridden for names with no OTHER same-named language they'd
# be conflated with; genuinely disambiguating ones (e.g. "Tonga (Tonga
# Islands)" vs. "Tonga (Nyasa)") are left as ISO names them.
_DISPLAY_OVERRIDES = {
    "Modern Greek (1453-)": "Greek",
    "Malay (macrolanguage)": "Malay",
    "Nepali (macrolanguage)": "Nepali",
    "Swahili (macrolanguage)": "Swahili",
    "Occitan (post 1500)": "Occitan",
}


def _lookup_one(text: str) -> Optional[str]:
    key = text.strip().lower()
    if not key:
        return None
    canonical = _BY_NAME.get(key)
    if canonical is not None:
        return canonical
    try:
        return pycountry.languages.lookup(key).name
    except LookupError:
        return None


def _resolve_segment(segment: str) -> list[str]:
    """Resolve one comma-separated fragment to one or more canonical
    language names. The whole fragment is tried as a single language first
    (so real multi-word names resolve as themselves); only if that fails is
    it split on secondary separators and each piece tried individually —
    this is what turns a comma-less "english and spanish" tag into two
    languages instead of one dropped, unrecognized fragment."""
    whole = _lookup_one(segment)
    if whole is not None:
        return [whole]

    pieces = [p for p in _SECONDARY_SPLIT_RE.split(segment) if p.strip()]
    if len(pieces) <= 1:
        return []  # genuinely unrecognized — drop it, as before

    return [name for name in (_lookup_one(p) for p in pieces) if name is not None]


def resolve_languages(language_field: str, languagecodes_field: str) -> list[str]:
    """Best-effort list of canonical ISO 639 language names for a station.
    Unrecognized free-text fragments (informal spellings Radio Browser
    stations sometimes use, e.g. "irani") are dropped rather than kept as
    ad-hoc buckets — the point of this is a fixed, canonical set."""
    found: dict[str, None] = {}  # insertion-ordered set

    for code in (languagecodes_field or "").split(","):
        code = code.strip().lower()
        if code and code in _BY_CODE:
            found[_BY_CODE[code]] = None

    for segment in (language_field or "").split(","):
        segment = segment.strip()
        if not segment:
            continue
        for name in _resolve_segment(segment):
            found[name] = None

    return [_DISPLAY_OVERRIDES.get(name, name) for name in found.keys()]
