# Multi-provider lyrics and Musixmatch

PyLrcGet keeps LRCLIB as the default lyrics source and supports Musixmatch as
an optional provider in the same priority matrix. Providers are tried only
when they are enabled in Settings → Lyrics → Lyrics Sources.

## Musixmatch transports

The Musixmatch settings panel provides two transports:

- **Website transport** — reads the public Musixmatch track page, as the
  reference desktop project does. It needs no user account or TIDAL
  credentials and obtains metadata/lyrics from the page's structured data.
- **Desktop API compatibility** — the legacy endpoint used by older desktop
  clients. It obtains a short-lived token and is kept as a best-effort fallback
  when the page transport cannot resolve a track.
- **Official API** — uses Musixmatch's documented API and requires an API key
  supplied by the user.

The website transport is the default configuration, but Musixmatch remains
disabled by default so an existing installation does not start making new
network requests without the user's consent.

## Matching behavior

Musixmatch search candidates are scored against the local artist, title,
album, duration, ISRC, and version metadata. Low-confidence candidates are
rejected before lyrics are fetched. The website transport currently returns
the plain lyrics exposed in the page data; the API/desktop compatibility
responses can also provide synced LRC lyrics when available.

The provider is intentionally isolated behind `MusixmatchClient` and
`MusixmatchProvider`, so the request/response handling remains fixture-testable
and does not leak into the download workers.

## Limitations

The desktop transport is an undocumented compatibility interface and can be
changed or rate-limited by Musixmatch. The official API is the supported path
when a valid key is available. PyLrcGet does not use TIDAL authentication or
the TIDAL lyrics endpoint.
