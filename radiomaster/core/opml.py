"""OPML import/export for podcast subscriptions.

OPML (https://opml.org) is the de-facto standard interchange format for
podcast/feed subscription lists -- every major podcast app can export/import
it, so this is how a user moves their subscriptions in or out of RadioMaster.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from xml.dom import minidom

from .podcast_api import PodcastResult


class OPMLError(RuntimeError):
    pass


def parse_opml(path: str) -> list[tuple[str, str]]:
    """Reads an OPML file and returns (title, feed_url) pairs for every
    outline that carries an xmlUrl -- recursing into nested outlines, since
    OPML lets subscriptions be grouped into folders."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise OPMLError(f"'{path}' is not valid OPML/XML: {exc}") from exc
    except OSError as exc:
        raise OPMLError(f"Could not read '{path}': {exc}") from exc

    body = tree.getroot().find("body")
    if body is None:
        raise OPMLError("OPML file has no <body> element.")

    feeds: list[tuple[str, str]] = []

    def walk(outline: ET.Element) -> None:
        feed_url = outline.get("xmlUrl")
        if feed_url:
            title = outline.get("title") or outline.get("text") or feed_url
            feeds.append((title, feed_url))
        for child in outline.findall("outline"):
            walk(child)

    for outline in body.findall("outline"):
        walk(outline)
    return feeds


def write_opml(path: str, podcasts: list[PodcastResult]) -> None:
    """Writes a flat OPML file listing every given podcast subscription."""
    opml = ET.Element("opml", version="2.0")
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = "RadioMaster Podcast Subscriptions"
    body = ET.SubElement(opml, "body")
    for podcast in podcasts:
        ET.SubElement(body, "outline", {
            "text": podcast.title,
            "title": podcast.title,
            "type": "rss",
            "xmlUrl": podcast.feed_url,
        })

    raw = ET.tostring(opml, encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(pretty)
    except OSError as exc:
        raise OPMLError(f"Could not write '{path}': {exc}") from exc
