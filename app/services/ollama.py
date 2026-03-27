from __future__ import annotations

import json
from asyncio import sleep
from typing import Any, Awaitable, Callable

import httpx

from app.core.config import ModelConfig


class OllamaClient:
    def __init__(self, config: ModelConfig) -> None:
        self._config = config

    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        on_chunk: Callable[[dict[str, str]], Awaitable[None]] | None = None,
        on_retry: Callable[[int, Exception], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        body = {
            "model": self._config.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a deterministic media organizer assistant. Reply only with valid JSON matching the provided schema.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "stream": True,
            "format": schema,
            "options": {
                "temperature": self._config.temperature,
            },
        }

        last_error: Exception | None = None
        total_attempts = self._config.retry_attempts + 1

        for attempt in range(1, total_attempts + 1):
            content_chunks: list[str] = []
            thinking_chunks: list[str] = []
            try:
                async with httpx.AsyncClient(timeout=self._config.request_timeout_seconds) as client:
                    async with client.stream("POST", f"{self._config.base_url.rstrip('/')}/api/chat", json=body) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.strip():
                                continue
                            payload = json.loads(line)
                            message = payload.get("message", {})
                            content_chunk = str(message.get("content", ""))
                            thinking_chunk = str(message.get("thinking", ""))
                            if content_chunk:
                                content_chunks.append(content_chunk)
                            if thinking_chunk:
                                thinking_chunks.append(thinking_chunk)
                            if on_chunk and (content_chunk or thinking_chunk):
                                await on_chunk(
                                    {
                                        "content": "".join(content_chunks),
                                        "thinking": "".join(thinking_chunks),
                                    }
                                )
                            if payload.get("done"):
                                break

                content = "".join(content_chunks).strip()
                if not content:
                    raise ValueError("Ollama returned an empty streamed response")

                return json.loads(content)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= total_attempts:
                    break
                if on_retry:
                    await on_retry(attempt, exc)
                if on_chunk:
                    await on_chunk({"content": "", "thinking": ""})
                await sleep(min(attempt, 2))

        raise RuntimeError(f"Ollama request failed after {total_attempts} attempts: {last_error}") from last_error
