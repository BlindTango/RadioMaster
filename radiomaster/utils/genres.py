"""Maps a station's raw Radio Browser tags to a fixed, canonical set of
music/format genres, so "By Genre" browsing groups stations by a recognizable
genre instead of by whatever free-text tag a station happened to be
uploaded with.

Radio Browser's `tags` field is entirely freeform, user-submitted text —
alongside real genres it commonly contains decades ("80s"), moods ("chill",
"party"), languages/countries, city names, station call signs, and one-off
words that aren't a genre at all. There is no ISO-style standard for genres
the way there is for languages/countries, so this is a hand-curated taxonomy
(similar in spirit to KNOWN_NETWORKS in station_api.py) rather than a lookup
against a third-party database. Unrecognized tags are dropped rather than
kept as ad-hoc groups — same philosophy as utils/iso_languages.py.
"""

from __future__ import annotations

CANONICAL_GENRES = [
    "Pop", "Rock", "Classic Rock", "Hard Rock", "Alternative", "Indie",
    "Punk", "Metal", "Progressive Rock",
    "Hip Hop", "R&B", "Soul", "Funk", "Disco",
    "Jazz", "Blues", "Classical", "Opera",
    "Country", "Folk", "Bluegrass",
    "Electronic", "Dance", "House", "Techno", "Trance", "Drum & Bass",
    "Dubstep", "Ambient", "Chillout",
    "Reggae", "Ska", "Latin", "Salsa", "World",
    "Gospel", "Christian",
    "Oldies", "Classic Hits", "Adult Contemporary", "Easy Listening", "Lounge",
    "K-Pop", "J-Pop",
    "Children's", "Instrumental", "Top 40", "Soundtrack",
    "News", "Talk", "Sports", "Comedy", "Business", "Educational",
    "Community", "Public Radio", "College Radio", "Weather", "Religious",
]

# lowercase variant/alias -> canonical name. Every canonical name is
# included mapped to itself so an exact (case-insensitive) tag match always
# resolves without needing a separate alias entry.
_ALIASES: dict[str, str] = {name.lower(): name for name in CANONICAL_GENRES}
_ALIASES.update({
    "classicrock": "Classic Rock",
    "classic-rock": "Classic Rock",
    "hardrock": "Hard Rock",
    "hard-rock": "Hard Rock",
    "altrock": "Alternative",
    "alt rock": "Alternative",
    "alt-rock": "Alternative",
    "alternative rock": "Alternative",
    "indie rock": "Indie",
    "indierock": "Indie",
    "prog rock": "Progressive Rock",
    "progrock": "Progressive Rock",
    "heavy metal": "Metal",
    "heavymetal": "Metal",
    "hip-hop": "Hip Hop",
    "hiphop": "Hip Hop",
    "rap": "Hip Hop",
    "rnb": "R&B",
    "r and b": "R&B",
    "rhythm and blues": "R&B",
    "classical music": "Classical",
    "classic": "Classical",
    "opera music": "Opera",
    "country music": "Country",
    "country western": "Country",
    "folk music": "Folk",
    "edm": "Electronic",
    "electro": "Electronic",
    "electronica": "Electronic",
    "dance music": "Dance",
    "deep house": "House",
    "tech house": "House",
    "drum and bass": "Drum & Bass",
    "dnb": "Drum & Bass",
    "d&b": "Drum & Bass",
    "downtempo": "Chillout",
    "chill": "Chillout",
    "chill out": "Chillout",
    "reggaeton": "Reggae",
    "dancehall": "Reggae",
    "worldmusic": "World",
    "world music": "World",
    "gospel music": "Gospel",
    "christian music": "Christian",
    "christian rock": "Christian",
    "praise": "Christian",
    "worship": "Christian",
    "oldie": "Oldies",
    "oldies music": "Oldies",
    "classichits": "Classic Hits",
    "classic hit": "Classic Hits",
    "greatest hits": "Classic Hits",
    "adultcontemporary": "Adult Contemporary",
    "ac": "Adult Contemporary",
    "easy listening music": "Easy Listening",
    "kpop": "K-Pop",
    "k pop": "K-Pop",
    "jpop": "J-Pop",
    "j pop": "J-Pop",
    "children": "Children's",
    "childrens": "Children's",
    "kids": "Children's",
    "kids music": "Children's",
    "instrumentals": "Instrumental",
    "top40": "Top 40",
    "top 40 music": "Top 40",
    "hits": "Top 40",
    "soundtracks": "Soundtrack",
    "movie soundtrack": "Soundtrack",
    "film score": "Soundtrack",
    "news talk": "News",
    "newsradio": "News",
    "talk radio": "Talk",
    "talkradio": "Talk",
    "sport": "Sports",
    "sports radio": "Sports",
    "comedy radio": "Comedy",
    "business news": "Business",
    "education": "Educational",
    "educational radio": "Educational",
    "community radio": "Community",
    "public": "Public Radio",
    "public broadcasting": "Public Radio",
    "college": "College Radio",
    "university radio": "College Radio",
    "religion": "Religious",
    "religious music": "Religious",
})


def resolve_genres(tags: str) -> list[str]:
    """Best-effort list of canonical genres for a station's raw tag string.
    Unrecognized fragments (moods, decades, place names, one-off words) are
    dropped — the point is a fixed, meaningful set to browse by."""
    found: dict[str, None] = {}
    for tag in (tags or "").split(","):
        key = tag.strip().lower()
        if not key:
            continue
        canonical = _ALIASES.get(key)
        if canonical is not None:
            found[canonical] = None
    return list(found.keys())
