# Jellyfin Torrent Organizer

Independent API service that scans torrent drop folders, uses Ollama to classify media, resolves Jellyfin target paths, and moves files into movie or series libraries.

## What It Does

1. Loads local path and model config from `config/`.
2. Scans torrent roots for video files, including files inside torrent folders.
3. Uses Ollama to classify every candidate as `movie`, `series`, or `skip`.
4. Uses Ollama again to choose the best matching existing library path from the configured target root.
5. Builds Jellyfin-friendly target paths.
6. Runs in `dryRun` mode by default.
7. Logs every run to `logs/` and writes a summary report to `reports/`.

## API

- `GET /health` health check
- `POST /runs` start a run
- `GET /runs/current` get current or latest run progress, including live AI output and current logs
- `GET /runs/current/logs` get current or latest run logs
- `GET /runs/current/ai` stream raw Ollama output as plain text
- `GET /logs` stream live current-run updates, including AI output and logs
- `GET /runs/{run_id}` get a specific run summary
- `GET /runs/{run_id}/logs` get a specific run log stream snapshot

Example start request:

```json
{
  "dryRun": true,
  "replaceExisting": true
}
```

## Jellyfin Layout Goal

- Movies: `<movies_root>/<Movie Title (Year)>/<Movie Title (Year)>.ext`
- Series: `<series_root>/<Show Name>/Season 01/<Show Name - S01E01.ext>`

## Ollama Config

- Provider: `ollama`
- Base URL: `http://10.69.1.131:11434`
- Model: `gpt-oss:20b-ctx`

## Docker Compose

Start the API:

```bash
docker compose up --build -d
```

Call the API:

```bash
curl -X POST http://localhost:18327/runs -H 'content-type: application/json' -d '{"dryRun":true}'
curl http://localhost:18327/runs/current
curl http://localhost:18327/runs/current/logs
curl -N http://localhost:18327/runs/current/ai
curl -N http://localhost:18327/logs
```

While a run is active, `GET /runs/current` now includes:

- `active_step`
- `active_item_path`
- `ai_output`
- `logs`

`GET /logs` is an SSE stream that pushes the full current run snapshot whenever it changes, including:

- progress counts
- current item
- live `ai_output`
- accumulated `logs`

`GET /runs/current/ai` is a raw text stream for debugging. It prints Ollama output in real time as it is generated.

## Notes

- One run is allowed at a time.
- Existing target files can be replaced when `replaceExisting` is true.
- Low-confidence AI results are skipped and logged.
- The service is config-driven and stays independent from n8n.
