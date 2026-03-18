# Contract: Public Memory Pages

**Feature**: `/Users/tcai/Projects/Bibliotalk/specs/003-discord-bot/spec.md`
**Created**: 2026-03-07
**Scope**: Resolve one public memory page for one EverMemOS MemCell (`memory_id`)

This contract defines the request and response shape for the unified Memories API HTML page used by DM citations.

## Route

- Method: `GET`
- Path: `/memories/{memory_id}`

Where:
- `memory_id = {agent-slug}_{timestamp}`
- `agent_slug` is the agent slug (EverMemOS `user_id`)
- `timestamp` is a compact UTC timestamp (`YYYYMMDDTHHMMSSZ`) matching the MemCell's `timestamp`

## Resolution Rules

1. Parse `memory_id` into `agent-slug` and `timestamp`.
2. Resolve the matching MemCell from EverMemOS (scoped by `user_id=agent_slug` and exact timestamp).
3. Resolve the MemCell's `group_id` (treated as `source_id`) and load the matching local `Source`.
4. Load the full ordered chunk/segment sequence for the source from SQLite, then split that sequence into MemCells by EverMemOS cell timestamps to obtain the chunks belonging to this MemCell.
5. Render exactly one page containing:
   - the agent slug
   - the single MemCell payload returned by EverMemOS
   - the corresponding local excerpt(s) (chunks/segments)
   - a link to the original source at the reconstructed timepoint when applicable (e.g. YouTube `t=...s`)
6. Return `404` when the MemCell cannot be resolved.

## Response Requirements

- The page MUST correspond to exactly one memory item.
- The page MUST NOT include unrelated memories or broader navigation chrome.
- The page MUST include a link to the original source timepoint when applicable.
- The page MUST be publicly readable without Discord authentication.

## Failure Modes

- Invalid `memory_id` → `400`
- Memory not found → `404`
- EverMemOS unavailable → `503`
- Local source/segment lookup failure after valid memory lookup → `500` with structured logging
