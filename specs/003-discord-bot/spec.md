# Feature Specification: YouTube → EverMemOS → Discord Agent Bots

**Feature Branch**: `003-discord-bot`
**Created**: 2026-03-07
**Status**: Approved (Implemented)
**Approved**: 2026-03-15
**Input**: Design document: DESIGN.md

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Ingest a YouTube Channel Into EverMemOS (Priority: P1)

An operator registers an agent (e.g. Alan Watts) with one or more YouTube channel or playlist subscriptions. The system continuously discovers new videos, fetches transcripts, chunks them into stable segments, persists verbatim evidence locally, and memorizes each segment in EverMemOS under the agent's unique identity. The operator can also trigger a one-off re-ingest of any single video.

**Why this priority**: Without ingestion, no other capability exists. Everything downstream — DM chat, feed posting, grounding validation — depends on a populated EverMemOS and a consistent local evidence cache.

**Independent Test**: Configure a test agent with a single YouTube channel subscription and poll once. Confirm EverMemOS receives chunked memories with correct `group_id` and `message_id`, and that SQLite contains source metadata, segment text, and transcript-batch rows.

**Acceptance Scenarios**:

1. **Given** a registered agent with a YouTube subscription, **When** the collector polls the subscription, **Then** newly discovered videos are enqueued and each transcript segment is persisted in SQLite and memorized in EverMemOS under the correct `group_id`.
2. **Given** a video already ingested, **When** the collector polls again, **Then** the same `video_id` is not re-ingested and no duplicate memories appear in EverMemOS.
3. **Given** an operator triggers manual single-video ingestion, **When** the video was previously ingested, **Then** existing EverMemOS memories for that `group_id` are deleted first, transcript is re-fetched, and memories are re-inserted cleanly.
4. **Given** a video with no available transcript, **When** the collector attempts ingest, **Then** the failure is recorded in `ingest_state` and the video is skipped without corrupting other in-progress ingest operations.
5. **Given** EverMemOS is temporarily unavailable during ingest, **When** chunk memorization fails, **Then** local SQLite state is preserved intact so the operator can retry without data loss.

---

### User Story 2 — Publish Video Feed Into a Discord Channel Thread (Priority: P2)

For each successfully ingested video, the system posts one parent message with the video title and YouTube link to the agent's designated feed channel, then creates a thread under that message and populates it with batched transcript messages derived from speaker-continuity and silence-gap grouping. Rerunning the publish path for the same video produces no duplicate posts or threads.

**Why this priority**: The feed provides the primary discovery surface for subscribers, and idempotency correctness here determines the quality of the Discord UX over time.

**Independent Test**: In a test guild with the feed channel pre-configured, ingest one video and run the publisher. Confirm exactly one parent message and one thread are created, and that transcript batch messages appear in sequence order. Re-run the publisher and confirm no duplicates.

**Acceptance Scenarios**:

1. **Given** a newly ingested video, **When** the feed publisher runs, **Then** exactly one parent message containing the video title and URL is posted to the agent's feed channel.
2. **Given** the parent message is posted, **When** the thread publisher runs, **Then** exactly one thread is created and transcript batch messages are posted in source sequence order.
3. **Given** the same video's feed has already been published, **When** the publisher runs again, **Then** no duplicate parent message, thread, or transcript-batch post is created.
4. **Given** thread creation succeeds but batch posting fails midway, **When** the publisher retries, **Then** already-posted batch messages are not re-posted; only the remaining batches are sent.
5. **Given** multiple newly ingested videos for the same agent, **When** the publisher runs, **Then** Discord rate limits are respected through sequential posting, not concurrent burst.

---

### User Story 3 — Grounded Private Talk Threads With Multiple Characters (Priority: P3)

A Discord user DMs the Bibliotalk bot and starts a talk via `/talk Character A, Character B, ...`. The bot creates a private thread under the guild's Talk Hub channel `#bibliotalk`, invites the user, and routes the user's thread messages to one or more selected characters. Each character response is grounded in EverMemOS evidence, uses inline markdown memory links, and validates every link and quoted span before sending. If no usable evidence exists the character explicitly says so.

**Why this priority**: The private talk UX is the highest-value user-facing capability and the proof of the "言必有據" (evidence-backed speech) principle.

**Independent Test**: DM the bot and run `/talk Alan Watts`. In the created private thread, ask a question known to match an already-ingested transcript segment. Confirm the response contains an inline markdown link in the form `[text](memory_url)`, the linked page shows exactly one EMOS memory item with the video timepoint, and the generated quote is a substring of the cached verbatim segment text.

**Acceptance Scenarios**:

1. **Given** `/talk Alan Watts`, **When** the bot creates the talk, **Then** the talk is a private thread under `#bibliotalk` and the user is invited.
2. **Given** a thread question with a known matching transcript segment, **When** the character responds, **Then** the response contains at least one inline markdown link of the form `[text](https://www.bibliotalk.space/memories/{id})`.
3. **Given** a response containing a memory link, **When** the linked page is loaded, **Then** it shows exactly one EverMemOS MemCell and a link to the original source at the reconstructed timepoint when applicable.
4. **Given** a question with no supporting evidence in EverMemOS, **When** the character responds, **Then** the character explicitly states it lacks relevant evidence rather than fabricating an answer.
5. **Given** a generated response contains a memory link that does not resolve to a valid EMOS memory, **When** the citation validator runs, **Then** the invalid link is stripped before the message is sent to the user.
6. **Given** a generated quoted span is not a substring of the cached local segment text, **When** the citation validator runs, **Then** the bad quote is stripped or the link is removed before sending.
7. **Given** a multi-character talk, **When** the bot routes a message to Character A, **Then** only Character A's memories are retrieved; no cross-character data leaks.

---

### Edge Cases

- What happens when a YouTube channel is deleted or a video becomes private after its transcript is already cached in SQLite?
- How does the system handle transcripts with no speaker labels or auto-generated captions that contain errors?
- What happens when Discord returns a rate-limit error during batch posting of a long video thread?
- What happens when two polling cycles discover the same new video simultaneously?
- How does the system handle EverMemOS returning an empty result set for a well-formed query?
- What happens when the agent slug changes (never allowed — slugs are immutable once deployed)?

## Requirements *(mandatory)*

### Functional Requirements

#### Ingestion

- **FR-001**: The system MUST continuously discover new YouTube videos for each agent by polling registered channel and playlist subscriptions using `yt-dlp` flat extraction.
- **FR-002**: The system MUST fetch transcripts for discovered videos using `youtube-transcript-api` and metadata using `yt-dlp`.
- **FR-003**: The system MUST split transcript text into stable, sentence-aware segments of approximately 1,200 characters.
- **FR-004**: The system MUST compute each segment's `create_time` as `video_published_at + transcript_chunk_start_offset_seconds`.
- **FR-005**: The system MUST persist each source, segment, and derived transcript-batch in a local SQLite evidence cache.
- **FR-006**: The system MUST deduplicate segments by agent, video ID, sequence number, and SHA-256 content hash; re-inserting an identical segment MUST NOT produce a duplicate row.
- **FR-007**: The system MUST memorize each segment into EverMemOS using stable `group_id = {emos_user_id}:youtube:{video_id}` and `message_id = {emos_user_id}:youtube:{video_id}:seg:{seq}` identifiers.
- **FR-008**: Automated polling MUST treat `video_id` as the immutable no-reingest key; a known `video_id` MUST NOT be re-ingested automatically.
- **FR-009**: The system MUST support manual single-video ingestion by first deleting all existing EverMemOS memories for that video's `group_id`, then re-ingesting from scratch.
- **FR-010**: The system MUST apply exponential backoff after repeated per-subscription failures and record failure state in `ingest_state`.
- **FR-011**: The system MUST group adjacent transcript segments into `transcript_batches` using speaker-continuity and silence-gap threshold rules for later Discord posting.

#### Discovery

- **FR-012**: Each agent MUST be able to own multiple YouTube subscriptions (channels and playlists).
- **FR-013**: The system MUST persist a per-subscription discovery cursor in `ingest_state` and only enqueue videos not yet seen since the last successful poll.
- **FR-014**: Poll intervals MUST be configurable per subscription (default 15–60 minutes).
- **FR-015**: The system SHOULD support YouTube RSS as an optional fallback when `yt-dlp` extraction is unreliable for a given source.

#### Discord Feed

- **FR-016**: For each newly ingested video, the system MUST post exactly one parent message containing the video title and YouTube link to the agent's designated feed channel.
- **FR-017**: The system MUST create exactly one thread per video under the parent message and post transcript-batch messages in sequence order.
- **FR-018**: Feed batch messages MUST contain original verbatim transcript text; EMOS-generated summaries MUST NOT appear in feed posts.
- **FR-019**: The system MUST never post a duplicate parent message, thread, or transcript-batch post for the same video (idempotent publication).
- **FR-020**: Discord posting MUST be sequential per agent to respect rate limits; concurrent bursting across multiple videos is not permitted.
- **FR-021**: The system MUST track Discord post state in SQLite (`discord_posts`) and resume from the last successfully posted batch if a thread-posting run fails partway through.

#### Talks (DM → Private Threads)

- **FR-022**: Users MUST initiate private conversations by DMing the bot and invoking `/talk Character A, [Character B...]`.
- **FR-023**: `/talk` MUST create (or resume) a private thread under the guild Talk Hub channel `#bibliotalk` and invite the user.
- **FR-024**: A user message posted inside a talk thread MUST be routed to one or more selected characters; users MAY override routing by prefixing a message with `@character-name`.
- **FR-025**: When routing a user message to a character, the system MUST search EverMemOS for relevant evidence before generating any response.
- **FR-026**: The system MUST rerank retrieved EverMemOS candidate segments using BM25 against the user query.
- **FR-027**: Every non-trivial factual claim in a character response MUST be expressed as an inline markdown link of the form `[text](https://www.bibliotalk.space/memories/{id})`.
- **FR-028**: Character responses MUST NOT use citation indices (e.g., [1], [2]) or a trailing `Sources:` section.
- **FR-029**: The system MUST validate each `memory_url` in a generated response resolves to a real EMOS memory belonging to the chosen character before sending.
- **FR-030**: The system MUST validate that any quoted span in the response is a substring of the corresponding cached local segment text before sending.
- **FR-031**: If no usable evidence remains after validation, the character MUST respond that it could not find relevant supporting evidence.
- **FR-032**: Memory retrieval MUST be strictly scoped to the chosen character; cross-character memory access is forbidden.
- **FR-033**: Users MUST be able to list their recent talks via `/talks` in DM, returning thread links and participant names (no keyword filter in MVP).

#### Memories (Public Pages)

- **FR-034**: The system MUST serve public memory pages at `https://www.bibliotalk.space/memories/{id}` that contain exactly one EverMemOS MemCell and the corresponding source excerpt(s), plus a link to the original source at the reconstructed timepoint when applicable.

#### Operations

- **FR-035**: The system MUST run as a single Discord bot process for MVP (one bot identity that can play multiple characters).
- **FR-036**: Global and per-source ingest concurrency MUST be configurable and bounded, where a source is a single channel or playlist subscription.
- **FR-037**: Required secrets (`EMOS_BASE_URL`, `EMOS_API_KEY`, `DISCORD_TOKEN`) MUST be injected through environment variables.

### Key Entities

- **Agent**: Represents an individual whose content is tracked. Has a stable UUID `agent_id`, a human-readable stable slug (e.g. `alan-watts`), a `display_name`, a `persona_summary`, and a lifecycle `status`.
- **Subscription**: Binds an agent to a YouTube channel or playlist URL. Carries its own `poll_interval_minutes` and `is_active` flag.
- **Source**: A single YouTube video associated with an agent. Stores the YouTube `video_id`, computed `group_id`, video metadata, and transcript ingest status.
- **Segment**: One atomic chunk of a video transcript. Identified by `segment_id`, sequence `seq`, verbatim `text`, content `sha256`, millisecond offsets, and EMOS `create_time`.
- **TranscriptBatch**: A locally computed grouping of adjacent segments by speaker continuity and silence gap for Discord feed posting. Not derived from EMOS MemCells.
- **IngestState**: Per-subscription discovery cursor tracking last seen video, last polled time, failure count, and next retry time.
- **DiscordMap**: Associates an agent with its Discord guild, feed channel, and bot application identifiers.
- **DiscordPost**: Records whether each `(source, batch)` pair has been posted to Discord, enabling idempotent retry.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: New videos on a subscribed channel or playlist are discovered and fully ingested into EverMemOS and SQLite within two polling cycles of publication.
- **SC-002**: Re-running automated ingestion for any agent produces zero new EverMemOS memories or SQLite rows for already-known videos.
- **SC-003**: Re-running the Discord feed publisher for any video produces zero duplicate parent messages, threads, or transcript-batch posts.
- **SC-004**: At least 95% of talk-thread responses to questions with known matching transcripts include a valid inline memory link that resolves to the correct EMOS memory page.
- **SC-005**: No talk-thread response ever includes a memory link to a memory belonging to a different agent.
- **SC-006**: When no supporting evidence exists, 100% of bot responses explicitly decline to answer rather than fabricating content.
- **SC-007**: A single-video manual re-ingest completes without leaving orphaned EverMemOS memories from the previous ingest run.
- **SC-008**: The system recovers from a mid-thread Discord posting failure and completes the remaining batches on retry without duplicating already-posted messages.

## Scope & Boundaries

### In Scope (MVP)

- YouTube as the only content source.
- One Discord bot that can play multiple agents.
- One feed channel and feed thread UX per agent.
- Private talk threads grounded on EverMemOS + local verbatim cache, created under `#bibliotalk`.
- SQLite as the local evidence and state store.
- Gemini via ADK as the LLM runtime.
- Lightweight public memory pages at `bibliotalk.space/memories/`.

### Out of Scope (MVP)

- Voice chat of any kind.
- Matrix integration or transport.
- Non-YouTube content sources.
- Multi-agent group conversations.
- Multi-human room semantics.
- Persistent multi-turn conversation history beyond short recent DM context.

## Assumptions

- `emos_user_id` slugs are immutable once deployed; rename is not a supported operation.
- The EverMemOS API supports delete-by-`group_id` for manual re-ingest.
- YouTube video IDs are stable and globally unique.
- Public memory pages are served by the unified Memories API in `memory_service`.
- Discord token provisioning (one bot token for the deployment) is done by the operator out-of-band.
- A single SQLite file per deployment instance is sufficient for MVP scale.
- Silence-gap and speaker-label thresholds for transcript batching will be tuned empirically; reasonable defaults are chosen at implementation time.
