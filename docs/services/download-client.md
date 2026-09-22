# Incomplete-Download Detection

The legacy download-client module (`app/services/download_client.py`) and the
download-client API integration (qBittorrent / Transmission / Deluge clients,
`ENABLE_DOWNLOAD_CLIENT_CHECK`, `DOWNLOAD_CLIENT`, `QBT_*`, `TRANSMISSION_*`,
`DELUGE_*`) have been **removed**. JellySort no longer talks to any download
client's API and never stops seeding. In-progress downloads are detected purely
from the filesystem by looking for **incomplete-file markers** that download
clients leave next to (or on) files while they are still downloading.

## Marker-based detection

Detection lives in `app/services/scanner.py`. Two marker families are checked,
all matched case-insensitively:

1. **Suffix markers** — a sibling file named `<candidate name><marker>`, e.g.
   `Show.S01E01.mkv.!qB` for candidate `Show.S01E01.mkv`, **or the candidate's
   own name** when the client renamed the file itself (`Show.S01E01.mkv.!qB`
   with no `Show.S01E01.mkv` next to it — the standard qBittorrent /
   Transmission / uTorrent shape with "append extension to incomplete files"
   enabled). Renamed files whose stem after stripping the marker still has a
   video extension are reported as in-progress candidates so they show in the
   report as `In-progress download` skips instead of staying invisible:

   | Marker | Client that writes it |
   | --- | --- |
   | `.!qB` | qBittorrent |
   | `.!ut` / `.utpart` | uTorrent |
   | `.!bt` | BitTorrent (Windows mainline client) |
   | `.bc!` / `.bc` | BitComet |
   | `.bt!` | BitSpirit |
   | `.az!` | Vuze/Azureus |
   | `.part` | Transmission, rTorrent, Vuze/Azureus |
   | `.partial` | rTorrent (split parts) |
   | `.parts` | libtorrent (kept by Deluge) |
   | `.td` / `.xltd` | Xunlei/Thunder |
   | `.aria2` | aria2 control sidecar (sibling marker only — the sidecar itself stays hidden) |
   | `.incomplete` / `.downloading` | generic incomplete markers |
   | `.crdownload` / `.download` / `.opdownload` | Chrome / Safari / Opera partial downloads |
   | `.tmp` / `.temp` | generic temp downloads |

2. **Prefix markers** — the candidate's own name starts with an
   `incomplete.` / `incomplete$` prefix (Tixati writes `incomplete.Show.S01E01.mkv`
   while the file is downloading). Prefixed files are reported as in-progress
   candidates themselves.

`_is_in_progress_by_marker(path)` scans the parent directory once and returns
True when any sibling matches `<name><marker>` or `<prefix><name>`, setting
`CandidateItem.in_progress`. `_candidate_in_progress(path)` reports renamed
files (own name is `<video><marker>` / `<prefix><video>`) as in-progress
candidates; `_is_hidden_sidecar(path)` keeps control sidecars (`.aria2`) that
are never video data invisible.

## How the scan uses it

`app/services/scan_orchestrator.py` reads `ENABLE_INCOMPLETE_DOWNLOAD_DETECTION`
(via `_incomplete_detection_enabled()`, default **true**) during the scan loop.
Candidates flagged `in_progress` are skipped and recorded as items with
`item_type="skip"` and `reason="In-progress download"` (counted as skipped;
excluded from planned coverage). Zero-byte files are skipped separately with
`reason="Zero-byte file; download is incomplete or invalid"`. When the setting is
`false`, in-progress files are scanned like any other candidate.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `ENABLE_INCOMPLETE_DOWNLOAD_DETECTION` | `true` | Skip files that are still downloading (marker-based, see above). |

It is a **live** setting (see [backend/config](../backend/config.md)) — no
restart needed. Full reference in
[getting-started/configuration](../getting-started/configuration.md).

## Notes

- The confirm phase `stopping_seeding` no longer exists in the running code
  (nothing is ever stopped); the literal remains in the `ScanPlan.confirm_phase`
  schema only for backwards compatibility.
- The scan manager's matching by **label** (top-level folder/file name) is
  separate from marker detection and still applies for other skip reasons.