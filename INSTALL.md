# Installation + Update Guide for LLMs

Use this guide to install jellyfin-mcp-helper for a user as either:

1. an MCP tool, or
2. a skill.

This guide also handles existing installations and update flows.

## Rule: Ask First, Then Execute

Before running any install command, ask the user all required choices first in one message, collect answers, then execute.

## Step 1: Ask All Options Upfront

Ask the user this exact checklist before doing anything:

1. Install mode:
   - `mcp`
   - `skill`
   - `both`
2. Workspace path where project should be cloned (or existing repo path)
3. Skill install scope (if skill or both):
   - project-local: `.opencode/skills/...`
   - global: `~/.config/opencode/skills/...`
4. Network target:
   - local-only (`127.0.0.1`)
   - LAN (`LAN_IP`)
5. Config values:
   - `LAN_IP`
   - `PORT` (default usually `18328`)
   - qBittorrent integration (optional, but requires auth when enabled):
     - `QBT_WEBUI_URL`
     - `QBT_WEBUI_USER`
     - `QBT_WEBUI_PASS`
   - Jellyfin integration (optional, but requires API key when enabled):
     - `JELLYFIN_BASE_URL`
     - `JELLYFIN_API_KEY`

Treat qBittorrent and Jellyfin as optional integrations. If the user does not have these values yet, continue install and set URL placeholders to `not-configured` in the installed skill file.

Why these values exist:

- qBittorrent (`QBT_WEBUI_URL` + auth): used so the service can stop torrent activity before moving files. This is especially important when the media folder is also the download folder.
- Jellyfin (`JELLYFIN_BASE_URL` + `JELLYFIN_API_KEY`): used to trigger a Jellyfin library scan after moves complete so new file locations are picked up automatically.

Important:

- Jellyfin actions require `JELLYFIN_API_KEY`.
- qBittorrent actions require valid Web UI auth (`QBT_WEBUI_USER`/`QBT_WEBUI_PASS`).
- Do not place secrets inside the installed skill file; configure them in the project's `.env` file.

Do not run install/update commands until the user answers this checklist.

## Step 2: Detect Existing Running Install

Check if the service is already running:

```bash
docker ps --filter name=jellyfin-mcp-helper
```

### If container is already running

Ask the user:

"I found an existing running install. Do you want to:
1) update the skill only, or
2) update the project (git pull + restart docker), or
3) both?"

Then follow the matching flow:

- **Update skill only**: run only the skill install/update steps.
- **Update project only**: run git + docker update steps.
- **Both**: run project update first, then skill update.

### If container is not running

Continue with a normal install flow.

## Step 3: Ensure Repository Exists

If repo does not exist at chosen path, clone it:

```bash
git clone https://github.com/jellyfin-mcp-helper/jellyfin-mcp-helper.git /path/to/workspace/jellyfin-mcp-helper
```

If repo already exists, do not re-clone.

## Step 4: Project Update Flow (when requested)

Run from the repo path:

```bash
git pull
docker compose up -d --build
```

If compose files/images did not change, `--build` is still safe.

If user provided new qBittorrent or Jellyfin credentials/API key, also update `<CLONE_PATH>/.env` before restarting containers.

## Step 5A: Skill Install/Update Flow (if mode is `skill` or `both`)

Install target paths:

- Project-local: `.opencode/skills/jellyfin-mcp-helper/SKILL.md`
- Global: `~/.config/opencode/skills/jellyfin-mcp-helper/SKILL.md`

Create target directory:

```bash
mkdir -p <target-skill-dir>
```

Copy source skill file from the cloned repo root:

`<CLONE_PATH>/SKILL.md`

Then update all skill variables in copied content.

Required variables to replace:

- `{{CLONE_PATH}}`
- `{{LAN_IP}}`
- `{{PORT}}`
- `{{QBT_WEBUI_URL}}` (optional value allowed)
- `{{JELLYFIN_BASE_URL}}` (optional value allowed)

Then map values as follows:

- `{{CLONE_PATH}}` -> absolute clone path (for example `/home/user/work/jellyfin-mcp-helper`)
- `{{LAN_IP}}` -> user LAN IP
- `{{PORT}}` -> user service port
- `{{QBT_WEBUI_URL}}` -> user qBittorrent Web UI URL, or `not-configured`
- `{{JELLYFIN_BASE_URL}}` -> user Jellyfin URL, or `not-configured`

Use actual user values (not placeholders) in the final installed file.

Do not write secrets (such as `JELLYFIN_API_KEY`, `QBT_WEBUI_PASS`) into the skill file.
Store those only in `<CLONE_PATH>/.env`.

Before finishing, verify no placeholders remain in installed skill file.

## Step 5B: MCP Install/Update Flow (if mode is `mcp` or `both`)

Configure the MCP endpoint in user config:

- LAN mode: `http://{{LAN_IP}}:{{PORT}}/mcp`
- Local mode: `http://127.0.0.1:{{PORT}}/mcp`

Example config snippet:

```json
{
  "mcp": {
    "jellyfin-mcp-helper": {
      "url": "http://{{LAN_IP}}:{{PORT}}/mcp"
    }
  }
}
```

Substitute with actual values.

## Step 6: Verify

Run health checks after install/update.

### Service check

```bash
docker ps --filter name=jellyfin-mcp-helper
curl http://127.0.0.1:{{PORT}}/health
```

### MCP check (if mcp or both)

```bash
curl -X POST http://{{LAN_IP}}:{{PORT}}/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

For local-only installs, use `127.0.0.1`.

### Skill check (if skill or both)

Open OpenCode and verify `jellyfin-mcp-helper` appears in available skills.

If optional values were set to `not-configured`, tell the user they can update those two fields later by editing the installed `SKILL.md` and replacing:
- `{{QBT_WEBUI_URL}}` value
- `{{JELLYFIN_BASE_URL}}` value

Also remind the user what each field enables:
- `QBT_WEBUI_URL` + qBittorrent auth enables safe pre-move torrent handling.
- `JELLYFIN_BASE_URL` + `JELLYFIN_API_KEY` enables post-move library refresh.

If integration is enabled but credentials are missing, warn that:
- qBittorrent stop/seeding management will not run.
- Jellyfin library refresh will be skipped.

## Expected User-Facing Questions Template

Use this one-shot prompt to collect all inputs first:

"I can install jellyfin-mcp-helper for you. Please choose:
1) mode: mcp, skill, or both
2) clone path (or existing repo path)
3) skill scope (project-local or global) if using skill
4) network mode (local-only or LAN)
5) LAN_IP, PORT
6) optional qBittorrent setup: QBT_WEBUI_URL, QBT_WEBUI_USER, QBT_WEBUI_PASS
7) optional Jellyfin setup: JELLYFIN_BASE_URL, JELLYFIN_API_KEY
8) if optional setup is missing now, I will set URLs to `not-configured`, continue install, and tell you what functionality is limited

I will then check for an existing running container and, if found, ask whether to update skill, project, or both."
