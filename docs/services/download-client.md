# Download Client — `app/services/download_client.py`

qBittorrent integration over **MCP**. Used for two things:

1. Detecting **in-progress downloads** so the scan can skip them.
2. **Stopping seeding** before a move (so the torrent doesn't recreate files).

## `QbittorrentClient`

### Construction

`QbittorrentClient(base_url, api_key, user, password, paths_config)`

`QbittorrentClient.from_env(paths_config)` returns `None` unless:

- `ENABLE_DOWNLOAD_CLIENT_CHECK` is truthy (default true),
- `DOWNLOAD_CLIENT == "qbittorrent"`,
- `QBT_MCP_URL` is set.

### Methods

| Method | qBittorrent MCP tool | Purpose |
| --- | --- | --- |
| `list_in_progress_paths()` | `list_torrents {view: "all"}` | Paths of torrents with `progress < 0.999`. |
| `stop_seeding_for_paths(candidate_paths)` | `list_torrents {view: "seeding"}` then `stop_torrents {hashes}` | Stop seeding for torrents matching the candidate paths; returns the matched items. |
| `list_items(view)` | `list_torrents {view}` | Raw torrent list (parses the MCP text payload as JSON). |

`_call_tool` posts JSON-RPC `tools/call` to `QBT_MCP_URL`. Authentication is
either the `X-MCP-Key` header (when `QBT_MCP_API_KEY` is set) or HTTP Basic
auth from `QBT_WEBUI_USER` / `QBT_WEBUI_PASS`. Timeout is 20 s.

## Path normalization

qBittorrent reports paths as seen on its own host, which may not match the
container's mount points. `_normalize_qbt_path` reconciles them:

- Extracts the torrent folder name from the qBittorrent path and searches for a
  matching folder inside the configured `download_roots`
  (`PathsConfig.find_download_root_for_folder`), then rebuilds the path from
  that root.
- Without a `PathsConfig`, the path is returned as-is.

`_item_paths` collects candidate paths from `content_path`, `root_path`,
`download_path`, `save_path + name`, plus a fallback that joins each download
root with the torrent name.

## Matching helpers

- `_is_incomplete(item)` — `progress < 0.999`.
- `_extract_paths(items, paths_config)` — deduped, normalized paths.
- `_item_matches_paths(item, candidate_paths, paths_config)` — prefix-based
  overlap: a candidate matches when it equals an item path or one is a path
  prefix of the other.

## Related in-progress logic

The scan manager also matches by **label** (top-level folder/file
name) via `_candidate_release_labels` / `_path_name_labels`, so torrents whose
paths don't map cleanly into the container still get detected.
