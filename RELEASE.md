# Release Process

## Branch Model

| Branch | Purpose | Protect |
|--------|---------|---------|
| `dev` | Active development. Feature/fix branches merge here. | Optional |
| `prod` | Stable production. Only release-ready code. Always protected. | Yes |

## Flow

```
feature/fix branch  →  dev  →  prod  →  tag vX.Y.Z
```

## Release Steps

1. Ensure feature/fix branches are merged into `dev`.
2. Switch to `prod` and merge `dev`:
   ```bash
   git checkout prod
   git merge dev
   ```
3. Run tests:
   ```bash
   python3 -m pytest
   ```
4. Update version in `app/core/version.py`.
5. Update `CHANGELOG.md` under the new version heading.
6. Commit the release:
   ```bash
   git add -A
   git commit -m "chore: release vX.Y.Z"
   ```
7. Tag the release:
   ```bash
   git tag vX.Y.Z
   ```
8. Push everything:
   ```bash
   git push origin prod
   git push origin vX.Y.Z
   ```
9. Create a GitHub Release from tag `vX.Y.Z`.
10. Switch back to `dev` for continued development:
    ```bash
    git checkout dev
    git merge prod
    ```
    This ensures `dev` has the latest version bump and changelog.

## Versioning

- `app/core/version.py` is the single source of truth.
- Follow semantic versioning:
  - **Patch** (v0.2.1): bug fixes only.
  - **Minor** (v0.3.0): new features, non-breaking.
  - **Major** (v1.0.0): breaking config/API/MCP changes.

## Checklist

Before every release, verify:

- [ ] All tests pass (`python3 -m pytest`)
- [ ] Version updated in `app/core/version.py`
- [ ] `CHANGELOG.md` updated with the new version and date
- [ ] Docker image builds (`docker compose build`)
- [ ] Git tag created and pushed
- [ ] GitHub Release created
