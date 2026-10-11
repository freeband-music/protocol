"""Fake add-on serving canned data. Standard library only.

Usage: fake_addon.py --port N [--invalid]
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ARTIST = {"id": "fake:artist:1", "name": "Fake Artist", "popularity": 40}
ALBUM = {"id": "fake:album:1", "title": "Fake Album", "artists": [ARTIST], "year": 2020}
TRACKS = [
    {
        "id": f"fake:track:{n}",
        "title": f"Fake Track {n}",
        "artists": [ARTIST],
        "album": ALBUM,
        "trackNumber": str(n),
        "discNumber": 1,
        "durationMs": 180000,
    }
    for n in (1, 2)
]
MANIFEST = {
    "id": "org.freeband.fake",
    "name": "Fake add-on",
    "version": "0.1.0",
    "description": "Canned data for tests",
    "protocolVersion": "0.4.0",
    "resources": ["search", "meta", "stream"],
    "idPrefixes": ["fake:"],
    "configurable": False,
    "configurationRequired": False,
}


def routes(port: int, invalid: bool) -> dict[str, object]:
    stream = {
        "title": "Fake Artist - Fake Track 1.mp3",
        "sizeBytes": 7200000,
        "quality": {"codec": "mp3", "bitrateKbps": 320, "lossless": False},
        "match": {"confidence": 1.0, "kind": "exact"},
        "url": f"http://localhost:{port}/audio/1.mp3",
    }
    if invalid:
        del stream["url"]
    table: dict[str, object] = {
        "/manifest.json": MANIFEST,
        "/search": {"tracks": TRACKS, "albums": [ALBUM], "artists": [ARTIST]},
        "/meta/artist/fake:artist:1": {**ARTIST, "albums": [ALBUM]},
        "/meta/album/fake:album:1": {**ALBUM, "tracks": TRACKS},
    }
    for track in TRACKS:
        table[f"/meta/track/{track['id']}"] = track
        table[f"/stream/track/{track['id']}"] = {"status": "ok", "streams": [stream]}
    # A track outside the catalogue that is prepared on request.
    table["/stream/track/fake:track:3"] = {
        "status": "queued",
        "message": "Preparing; ask again later",
        "streams": [],
    }
    return table


NOT_READY = {"status": "not_found", "message": "Nothing playable right now", "streams": []}


def make_handler(table: dict[str, object]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            body = table.get(url.path)
            status = 200
            if url.path.startswith("/stream/track/") and not (
                query.get("title") and query.get("artist")
            ):
                status = 400
                body = {"error": {"code": "bad_request", "message": "title and artist are required"}}
            elif (
                url.path.startswith("/stream/track/")
                and query.get("queue", ["true"])[-1].lower() in ("false", "0")
                and isinstance(body, dict)
                and body.get("status") == "queued"
            ):
                body = NOT_READY  # queue=false: start nothing, answer what is ready now
            elif body is None:
                status = 404
                body = {"error": {"code": "not_found", "message": "Not found"}}
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: object) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--invalid", action="store_true")
    args = parser.parse_args()
    handler = make_handler(routes(args.port, args.invalid))
    ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
