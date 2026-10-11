# Freeband add-on protocol

Freeband is an open-source music client in the style of add-on based media
centres. The client contains no content and no sources. Everything it shows
and plays comes from add-ons that the user chooses to install.

This repository is the contract between the client and the add-ons:
`openapi.yaml` is the single definition of the protocol, and `conformance/`
checks a running add-on against it.

- Client: <https://github.com/freeband-music/web>
- Example metadata add-on: <https://github.com/freeband-music/addon-musicbrainz>

## The pieces

| Piece | What it does |
|---|---|
| Client | A static web app. Lets the user install add-ons by URL, search, browse and play. Holds no catalogue. |
| Protocol | This repository. Defines the requests the client makes and the JSON that add-ons return. |
| Metadata add-ons | Provide search and artist, album and track information. |
| Stream add-ons | Turn a track's details into playable URLs. |

An add-on is an HTTP server run by whoever operates it. A user may install
any number of add-ons of either type.

### How a play request flows

1. The user searches. The client sends the query to the installed metadata
   add-ons and shows the results.
2. The user picks a track. The client already has its details (title,
   artists, album, position, duration and, when known, the ISRC) from the
   metadata add-on.
3. The client sends those details to the installed stream add-ons as query
   parameters of a stream request.
4. A stream add-on answers with a list of playable streams, best first, each
   labelled with its quality and how confident the match is.
5. The client plays the first suitable stream.

Because the client passes the track's details along, metadata add-ons and
stream add-ons are independent of each other. A stream add-on does not need
to know which metadata add-on a track came from, and does no metadata lookups
of its own.

## The protocol

An add-on answers JSON over HTTP GET with `Access-Control-Allow-Origin: *`.
It is identified by its manifest URL.

### URL shape

```
{base}/{config}/manifest.json
{base}/{config}/search?q=...&type=track|album|artist
{base}/{config}/meta/artist/{id}
{base}/{config}/meta/album/{id}
{base}/{config}/meta/track/{id}
{base}/{config}/stream/track/{id}?title=...&artist=...
```

`{config}` is optional. It is one opaque path segment (base64url-encoded
JSON) that holds per-user settings, so an add-on needs no accounts or
sessions. Add-ons that need no settings serve the same routes without it.
An add-on that takes settings normally offers a configure page that produces
the personal URL. Treat such a URL as a secret if the settings include
credentials.

### Routes

| Route | Purpose |
|---|---|
| `/manifest.json` | Describes the add-on: ID, name, version, protocol version, the resources it serves and the ID prefixes it answers for. |
| `/search` | Searches tracks, albums and artists. `type` narrows the search to one kind. |
| `/meta/artist/{id}` | An artist with summaries of their albums. |
| `/meta/album/{id}` | An album with its tracks in order. |
| `/meta/track/{id}` | A single track. |
| `/stream/track/{id}` | Streams for a track, best first. The track's details are query parameters: `title` and `artist` (repeatable) are required; `albumTitle`, `albumArtist`, `trackNumber`, `discNumber`, `trackCount`, `durationMs`, `year`, `isrc` and `queue` are optional. |

The manifest's `resources` lists which of `search`, `meta` and `stream` the
add-on serves. A metadata add-on serves `search` and `meta`; a stream add-on
serves `stream`. Non-2xx responses carry an error object with a `code` and a
`message`.

### IDs

IDs are opaque strings with a prefix, for example `fake:track:1`. The prefix
belongs to the add-on that issued the ID. The client sends a request only to
add-ons whose manifest declares the resource and an entry in `idPrefixes`
that the ID starts with. An empty `idPrefixes` means any ID, which is the
norm for stream add-ons: to them the ID is opaque and useful only as a cache
key.

### Popularity

Artist, album and track summaries may carry `popularity`, a number from 0
(unknown to listeners) to 100 (among the most played). It is optional: leave
it out when the source has no such data. Clients use it to pick the top
search result and to mix the results of several metadata add-ons; scores
from different add-ons are comparable only roughly, so an add-on should
spread its scores over the whole range (a logarithmic scale suits play or
fan counts). Added in protocol 0.4.0; older clients ignore it.

### Stream responses

A stream response has a `status`, an optional `message` for the user and a
list of `streams`.

| Status | Meaning |
|---|---|
| `ok` | At least one stream is ready to play. |
| `queued` | Nothing is playable yet, but the add-on has started preparing the track; ask again later. |
| `not_found` | The add-on has nothing for this track. |

#### Asking only for what is ready: `queue=false`

The optional `queue` query parameter (boolean, default `true`) says whether
the add-on may start preparing a track that is not playable yet. With
`queue=false` the add-on must not start any work that changes state
elsewhere or outlives the request (no downloads, nothing put in a queue): it
answers `ok` with the streams that are playable right now, or `not_found`,
and never `queued`. Such a `not_found` means only that nothing is ready at
the moment; the same request without `queue=false` may still find or prepare
a stream. Clients use it to look ahead, for example to check a whole play
queue before it is played:

```
{base}/stream/track/fake:track:3?title=Fake+Track+3&artist=Fake+Artist&queue=false
```

Add-ons that predate protocol 0.3.0 ignore the parameter.

Each stream carries:

- `title` and, optionally, `sizeBytes`;
- `quality`: `codec`, `lossless`, and when known `bitrateKbps`, `bitDepth`
  and `sampleRateHz`;
- `match`: a `confidence` from 0 to 1 and a `kind` (`exact`, `edition` or `loose`);
- `url`: where the audio is fetched from.

### Versioning

`protocolVersion` in the manifest is semver and equals `info.version` in
`openapi.yaml`. Additive changes keep the major version. Clients ignore
unknown fields, and refuse an add-on with a newer major version and say why.

## Writing an add-on

An add-on can be written in any language. It has to:

1. Serve the routes for the resources it declares, as JSON over HTTP GET.
2. Send `Access-Control-Allow-Origin: *` on every response, because the
   client is a web page on another origin.
3. Return bodies that validate against the schemas in `openapi.yaml`.
4. Serve the routes under a `{config}` segment if it needs per-user settings.

`conformance/fake_addon.py` is a complete add-on in about a hundred lines of
standard-library Python and is a reasonable starting point.

## Conformance checker

Start your add-on, then run the checker against its base URL (including the
`{config}` segment if it needs one):

```
nix develop -c just conformance http://localhost:8000 --query "some song"
```

Without Nix, only [uv](https://docs.astral.sh/uv/) is needed:
`uv run conformance/run.py URL [options]`.

The checker reads the manifest, then exercises each declared resource. For a
metadata add-on it searches with `--query` and follows the results. A
stream-only add-on has no track of its own to test with, so describe one:

```
just conformance http://localhost:8000 --title "Song" --artist "Artist" --album-title "Album"
```

For a stream add-on it sends the stream request twice, the second time with
`queue=false`, and fails if that answer is `queued`. With `--cached-only` it
sends only the `queue=false` request, so the add-on never starts preparing a
track. It prints one line per
route and exits 0 when every declared resource
validates against the schema, 1 otherwise.

### The fake add-on

```
python3 conformance/fake_addon.py --port 8765            # valid responses
python3 conformance/fake_addon.py --port 8765 --invalid  # a deliberately broken stream response
just conformance http://localhost:8765
```

It serves all three resources with fixed data, which also makes it useful
for trying a client without any real add-on.

## Generating types

Do not write protocol types by hand; generate them from `openapi.yaml`.

```
# TypeScript
pnpm dlx openapi-typescript@7 openapi.yaml -o schema.gen.ts

# Python (pydantic v2)
uvx --from datamodel-code-generator datamodel-codegen \
  --input openapi.yaml --input-file-type openapi --output models.py \
  --output-model-type pydantic_v2.BaseModel --snake-case-field \
  --allow-population-by-field-name --target-python-version 3.12 \
  --use-standard-collections --use-union-operator
```

## Development

```
nix develop
just validate    # validate openapi.yaml as an OpenAPI document
just selftest    # check the conformance runner against the fake add-on
just test        # both
```

When changing the protocol, edit `openapi.yaml` first, bump `info.version`,
then update `conformance/` and this README.

## Responsibility

The protocol and the client are content-neutral: they contain no content and
name no source. Add-ons are independent software run by their operators.
Users are responsible for which add-ons they install, and for complying with
the law and with the terms of any service an add-on uses.

## Licence

MIT. See `LICENSE`.
