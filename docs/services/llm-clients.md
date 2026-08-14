# LLM Clients — `app/services/ollama.py` and `openrouter.py`

Two interchangeable LLM clients used as the external classifier / name
resolver. Both expose the same async interface, driven by `ModelConfig`.

## Shared interface

```python
async def generate_json(
    prompt: str,
    schema: dict[str, Any],
    on_chunk: Callable[[dict[str, str]], Awaitable[None]] | None = None,
    on_retry: Callable[[int, Exception], Awaitable[None]] | None = None,
) -> dict[str, Any]:
```

- `on_chunk` receives `{"content": …, "thinking": …}` accumulations during
  streaming (used to surface live "AI thinking" in run logs).
- `on_retry(attempt, exc)` is invoked before a retry.
- Both stream responses and parse the final content as JSON.

## OllamaClient

- **URL:** `{MODEL_BASE_URL}/api/chat`
- **Request:** `messages` with a system prompt ("You are a deterministic media
  organizer assistant…"), `stream: true`, `format: schema` (structured output),
  and `options.temperature`.
- Collects both `content` and `thinking` chunks.
- Retries with a short backoff (`min(attempt, 2)` seconds) up to
  `retry_attempts + 1` total attempts.

## OpenRouterClient

- **URL:** `https://openrouter.ai/api/v1/chat/completions`
- **Headers:** `Authorization: Bearer {OPENROUTER_API_KEY}`,
  `HTTP-Referer: https://github.com/jellysort/jellysort`,
  `X-Title: JellySort`.
- Requires `OPENROUTER_API_KEY` in the environment (raises otherwise).
- Uses streaming SSE deltas; a `reasoning` chunk is folded into `content` when
  no content delta is present.
- JSON robustness: if the raw content isn't valid JSON, it tries to extract the
  first `{…}` block.
- Retries with a growing backoff (`attempt * 5`, capped at 30 s).

## Configuration

Both are built from `ModelConfig` (`app/core/config.py`):

- `provider` (`ollama`/`openrouter`), `model`, `base_url`, `temperature`
- `retry_attempts`, `request_timeout_seconds`
- confidence thresholds: `classify_confidence_threshold` (0.65) and
  `path_confidence_threshold` (0.6) — LLM results below these are not accepted
  by callers.

## Where they are used

- `app/main.py` — external classifier path (`use_local_ai`) in scan flow.
- `app/services/normalizer.py` — LLM title resolution (`_resolve_with_ai`,
  `_get_ollama_client`).
