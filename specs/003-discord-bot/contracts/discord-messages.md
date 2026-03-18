# Contract: Discord Message Shapes

**Used by:** `services/discord_service/` · feed publishing and talk threads
**Date:** 2026-03-10

This document defines the Discord-side "message shapes" Bibliotalk relies on.

For the feed publisher, we keep strict Pydantic boundary models in `services/discord_service/src/bot/message_models.py`. For talks, the boundary is Discord interactions (slash commands) + thread messages, and the persistence contract is the SQLite tables (`talk_threads`, `talk_participants`).

---

## DM Slash Commands

### `/talk`

- **Context:** DM only
- **Argument:** `characters: str` (comma-separated)
  - Example: `/talk Alan Watts, Naval`
- **Result:** bot creates or resumes a **private thread** under a guild channel named `#bibliotalk`, invites the user, and returns a thread jump link.

### `/talks`

- **Context:** DM only
- **Arguments:** none
- **Result:** bot lists recent talks as thread jump links with participant names.

---

## Talk Threads (Inbound/Outbound)

### Inbound

- **Type:** `discord.Message`
- **Location:** `discord.Thread` (private thread under `#bibliotalk`)
- **Author:** non-bot user
- **Content:** raw message text
  - Override routing by prefixing with `@slug` (e.g. `@alan-watts …`).

### Outbound

- **Type:** Discord message posted into the same thread
- **Persona:** sent as a webhook message (preferred) with a character name, falling back to a bot message prefixed with `**Character Name**:`
- **Constraints:**
  - ≤ 2,000 characters per Discord message
  - Long responses are split at sentence boundaries
  - Grounding links are inline markdown links: `[visible text]({BIBLIOTALK_WEB_URL}/memories/{id})`
  - No citation indices and no trailing `Sources:` blocks

---

## Feed Publisher Boundary Models (Pydantic)

These models are defined in `services/discord_service/src/bot/message_models.py`.

### `FeedParentMessage`

- One parent feed message per ingested source.
- Fields: `agent_id`, `source_id`, `channel_id`, `text`

### `FeedBatchMessage`

- One transcript batch message posted inside a per-video thread.
- Fields: `agent_id`, `source_id`, `batch_id`, `thread_id`, `text`, `seq_label`
