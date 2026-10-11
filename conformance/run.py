# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "pyyaml", "jsonschema"]
# ///
"""Validate a running add-on against openapi.yaml.

Usage: run.py URL [--query Q] [--title T --artist A [--artist A ...] [--album-title T]]

A stream-only add-on has no track to test with; describe one with --title and
--artist.
"""

import argparse
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
import yaml
from jsonschema import Draft202012Validator

SPEC = Path(__file__).resolve().parent.parent / "openapi.yaml"


class Runner:
    def __init__(self, base: str, doc: dict) -> None:
        self.base = base
        self.doc = doc
        self.client = httpx.Client(timeout=30, follow_redirects=True)
        self.failed = False

    def report(self, result: str, route: str, detail: str = "") -> None:
        if result == "FAIL":
            self.failed = True
        print(f"{result} {route}" + (f"  {detail}" if detail else ""))

    def check(self, route: str, schema: str, params: dict | None = None, label: str = ""):
        """Fetch a route and validate it. Returns the body, or None on failure."""
        path, route = route, label or route
        try:
            response = self.client.get(self.base + path, params=params)
        except httpx.HTTPError as exc:
            self.report("FAIL", route, f"{type(exc).__name__}: {exc}")
            return None
        if response.status_code != 200:
            self.report("FAIL", route, f"HTTP {response.status_code}")
            return None
        try:
            body = response.json()
        except ValueError:
            self.report("FAIL", route, "body is not JSON")
            return None
        validator = Draft202012Validator(
            {"$ref": f"#/components/schemas/{schema}", "components": self.doc["components"]}
        )
        error = next(validator.iter_errors(body), None)
        if error is not None:
            path = "/".join(str(p) for p in error.absolute_path) or "(root)"
            message = error.message[:300]
            self.report("FAIL", route, f"{path}: {message}")
            return None
        if "access-control-allow-origin" not in response.headers:
            self.report("FAIL", route, "missing Access-Control-Allow-Origin header")
            return body
        self.report("PASS", route)
        return body


def first(items: object) -> dict | None:
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0]
    return None


def stream_params(track: dict) -> dict:
    """Query parameters of a stream request for a Track object."""
    album = track.get("album") or {}
    params = {
        "title": track.get("title"),
        "artist": [a["name"] for a in track.get("artists") or [] if a.get("name")],
        "albumTitle": album.get("title"),
        "trackNumber": track.get("trackNumber"),
        "discNumber": track.get("discNumber"),
        "trackCount": album.get("trackCount"),
        "durationMs": track.get("durationMs"),
        "year": album.get("year"),
        "isrc": track.get("isrc"),
    }
    return {name: value for name, value in params.items() if value not in (None, "", [])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--query", default="test")
    parser.add_argument("--title")
    parser.add_argument("--artist", action="append", default=[])
    parser.add_argument("--album-title")
    parser.add_argument(
        "--cached-only",
        action="store_true",
        help="send stream requests only with queue=false, so no download is started",
    )
    args = parser.parse_args()

    base = args.url.rstrip("/").removesuffix("/manifest.json")
    doc = yaml.safe_load(SPEC.read_text())
    runner = Runner(base, doc)

    manifest = runner.check("/manifest.json", "Manifest")
    if manifest is None:
        return 1
    ours = doc["info"]["version"].split(".")[0]
    theirs = str(manifest["protocolVersion"]).split(".")[0]
    if ours != theirs:
        runner.report("FAIL", "/manifest.json", f"protocolVersion major {theirs}, expected {ours}")
    resources = manifest["resources"]

    ids: dict[str, str | None] = {"track": None, "album": None, "artist": None}
    track: dict | None = None
    if "search" in resources:
        found = runner.check("/search", "SearchResponse", {"q": args.query})
        if found is not None:
            track = first(found.get("tracks"))
            ids = {kind: (first(found.get(kind + "s")) or {}).get("id") for kind in ids}

    if "meta" in resources:
        for kind, schema in (("artist", "Artist"), ("album", "Album"), ("track", "Track")):
            if ids[kind] is None:
                runner.report("SKIP", f"/meta/{kind}/{{id}}", "no id to test with")
                continue
            body = runner.check(f"/meta/{kind}/{quote(ids[kind], safe=':')}", schema)
            if kind == "track" and body is not None:
                track = body

    if "stream" in resources:
        track_id = (track or {}).get("id") or "conformance:track:1"
        params = stream_params(track) if track else {}
        if args.title or args.artist:
            track_id = "conformance:track:1"
            params = {"title": args.title, "artist": args.artist}
            if args.album_title:
                params["albumTitle"] = args.album_title
        if not params.get("title") or not params.get("artist"):
            runner.report("SKIP", "/stream/track/{id}", "no track; pass --title and --artist")
        else:
            route = f"/stream/track/{quote(track_id, safe=':')}"
            if not args.cached_only:
                runner.check(route, "StreamResponse", params)
            label = route + "?queue=false"
            body = runner.check(route, "StreamResponse", {**params, "queue": "false"}, label)
            if body is not None and body.get("status") == "queued":
                runner.report("FAIL", label, "status queued is not allowed with queue=false")

    return 1 if runner.failed else 0


if __name__ == "__main__":
    sys.exit(main())
