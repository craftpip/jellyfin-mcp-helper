from __future__ import annotations

import json
import os
from asyncio import sleep
from typing import Any, Awaitable, Callable

import httpx

from app.core.config import ModelConfig


class OpenRouterClient:
    def __init__(self, config: ModelConfig) -> None:
        self._config = config
        self._api_key = os.getenv("OPENROUTER_API_KEY")
        if not self._api_key:
            raise ValueError("OPENROUTER_API_KEY not set in environment")

    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        on_chunk: Callable[[dict[str, str]], Awaitable[None]] | None = None,
        on_retry: Callable[[int, Exception], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/jellyfin-download-organizer/jellyfin-download-organizer",
            "X-Title": "Jellyfin Download Organizer",
        }
        body = {
            "model": self._config.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a deterministic media organizer assistant. Reply only with valid JSON matching the provided schema. Schema: " + json.dumps(schema),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": self._config.temperature,
        }

        last_error: Exception | None = None
        total_attempts = self._config.retry_attempts + 1

        for attempt in range(1, total_attempts + 1):
            content_chunks: list[str] = []
            try:
                async with httpx.AsyncClient(timeout=self._config.request_timeout_seconds) as client:
                    async with client.stream("POST", "https://openrouter.ai/api/v1/chat/completions", json=body, headers=headers) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.strip() or line.strip() == "data: [DONE]":
                                continue
                            if line.startswith("data: "):
                                line = line[6:]
                            payload = json.loads(line)
                            delta = payload.get("choices", [{}])[0].get("delta", {})
                            content_chunk = str(delta.get("content", ""))
                            reasoning_chunk = str(delta.get("reasoning", ""))
                            if not content_chunk and reasoning_chunk:
                                content_chunk = reasoning_chunk
                            if content_chunk:
                                content_chunks.append(content_chunk)
                            if on_chunk and content_chunk:
                                await on_chunk(
                                    {
                                        "content": "".join(content_chunks),
                                        "thinking": "",
                                    }
                                )
                            if payload.get("choices", [{}])[0].get("finish_reason") == "stop":
                                break

                content = "".join(content_chunks).strip()
                if not content:
                    raise ValueError("OpenRouter returned an empty streamed response")

                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    import re
                    match = re.search(r'\{.*\}', content, re.DOTALL)
                    if match:
                        return json.loads(match.group())
                    raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= total_attempts:
                    break
                if on_retry:
                    await on_retry(attempt, exc)
                if on_chunk:
                    await on_chunk({"content": "", "thinking": ""})
                delay = min(attempt * 5, 30)
                await sleep(delay)

        raise RuntimeError(f"OpenRouter request failed after {total_attempts} attempts: {last_error}") from last_error