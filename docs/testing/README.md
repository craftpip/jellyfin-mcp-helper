# Testing

Backend (pytest) and frontend (Vitest) test suites.

- [Backend tests](backend.md) — `python3 -m pytest tests/`.
- [Corpus fixtures](corpus.md) — the obfuscated download-path regression corpus.

Run everything relevant:

```bash
python3 -m pytest tests/          # backend
cd app/ui/react && npm test       # frontend
```
