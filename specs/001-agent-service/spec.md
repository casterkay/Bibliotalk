# Feature Specification: Agent Service

**Feature**: `001-agent-service`  
**Created**: 2026-02-28  
**Last Updated**: 2026-03-06  
**Status**: Draft (implementation in progress; synced to `BLUEPRINT.md`)  
**Input**: User description: "agent service with ADK, EverMemOS, voice chat capability"

**Source of truth**: `BLUEPRINT.md`. If this spec conflicts with the current repository tree, follow the tree (per `BLUEPRINT.md`).

## Local E2E Note (SQLite + SQLAlchemy)

`BLUEPRINT.md` models the platform storage layer as a relational database. For local end-to-end development (“let me chat with ghosts”), this repo uses **SQLite** behind a **SQLAlchemy ORM** store, holding the same logical entities (`agents`, `profile_rooms`, `sources`, `segments`, `chat_history`, etc.). This does not change the user-facing behavior or contracts; it only changes the dev storage backend.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Private Text Chat with a Ghost (Priority: P1)

A user opens a private chat with a Ghost (e.g., Confucius) and asks a question. The Ghost searches its personal memory, responds conversationally in-character, and includes verifiable citations to the original source material (books, podcast transcripts, videos). Every factual claim in the Ghost's response links back to a specific passage from the Ghost's ingested content.

**Why this priority**: This is the foundational user experience of Bibliotalk. Without grounded text chat, no other feature (multi-agent discussions, voice calls) has value. A user must be able to converse with a single Ghost and trust the citations before any advanced interactions.

**Independent Test**: Can be fully tested by sending a message to a Ghost in a DM room and verifying the response contains inline citation markers that correspond to real, verifiable source passages.

**Acceptance Scenarios**:

1. **Given** a user has a private DM room with a figure Ghost, **When** the user sends a factual question (e.g., "What did you say about learning?"), **Then** the Ghost responds in-character with inline citation markers (e.g., superscript numbers), and each citation references a verifiable passage from the Ghost's source material.
2. **Given** a user sends a message to a Ghost, **When** the Ghost's memory contains no relevant evidence, **Then** the Ghost responds with an explicit acknowledgment that it has no evidence for that topic, rather than fabricating an answer.
3. **Given** a user has a group chat room with multiple participants (real users and Ghosts), **When** a user mentions a Ghost or addresses it directly, **Then** only the addressed Ghost responds, with grounded citations.
4. **Given** a Ghost is a member of a profile room (read-only public room), **When** a user attempts to send a message in that room, **Then** Matrix room permissions reject the message and no AI response is generated. Only pre-ingested verbatim content appears in profile rooms.
5. **Given** a Ghost produces a response with citations, **When** the system validates the citations, **Then** any citation whose quoted text does not match the original source passage is stripped from the response before delivery.

---

### User Story 2 - Multi-Agent Text Discussion (Priority: P2)

A user creates a discussion room with two or more Ghosts (e.g., Confucius and Aristotle) and sets a topic (e.g., "Ethics of AI"). The Ghosts autonomously request speaking turns and can request agent-to-agent preemption, while a room-level controller enforces one active speaker at a time. The user can observe, interject, and interrupt at any time; user speech always takes priority. Citations from all participating Ghosts are visible in the shared room.

**Why this priority**: Multi-agent discussions are a signature differentiator for Bibliotalk — enabling "conversations" between historical or contemporary figures that never happened. This builds on the single-Ghost chat foundation (P1) and reuses the same grounding and citation machinery.

**Independent Test**: Can be tested by starting a discussion with two Ghosts and a topic, then verifying that floor grants are serialized, agents use `REQUEST_FLOOR(force)` correctly, user interruption preempts active Ghost output immediately, and citations remain isolated per Ghost memory.

**Acceptance Scenarios**:

1. **Given** a user creates a discussion room with two or more Ghosts and specifies a topic, **When** the discussion starts, **Then** Ghosts submit `REQUEST_FLOOR` intents and the controller grants only one Ghost at a time to respond with grounded citations.
2. **Given** an ongoing multi-agent discussion, **When** the user sends a message in the room, **Then** any active Ghost stream is canceled and the user takes priority immediately.
3. **Given** an ongoing multi-agent discussion, **When** the configured number of turns is reached, **Then** the discussion concludes gracefully (no further automatic Ghost responses).
4. **Given** a multi-agent discussion, **When** Ghost A cites a source, **Then** that citation references Ghost A's memory only — never a passage from Ghost B's memory.
5. **Given** a user utterance directly mentions Ghost B, **When** the floor becomes available, **Then** Ghost B is strongly preferred for the next floor grant.
6. **Given** Ghost B is speaking and Ghost A submits `REQUEST_FLOOR(force=true)`, **When** force thresholds and rate limits pass, **Then** Ghost B is canceled and Ghost A takes the floor.
7. **Given** the user is speaking, **When** any Ghost submits `REQUEST_FLOOR`, **Then** `force=true` is rejected and only queued non-force requests are accepted.
8. **Given** a user issues a stop command during a discussion, **When** the command is processed, **Then** all Ghost responses in that room cease.

---

### User Story 3 - Voice Call with a Ghost (Priority: P3)

A user starts a voice call with a Ghost in a private room. The Ghost listens to the user's speech, searches its memory for relevant evidence, and responds in voice — in real-time. A text transcript of the conversation, including citations, is posted to a parallel text thread in the same room so the user can review sources after the call.

**Why this priority**: Voice interaction transforms Bibliotalk from a text-based Q&A tool into an immersive conversational experience. It depends on the text-chat grounding infrastructure (P1) being complete. Voice adds a new modality but reuses the same memory search and citation system.

**Independent Test**: Can be tested by starting a voice call with a single Ghost, speaking a question, and verifying that the Ghost responds in voice with audible speech, while a text thread in the same room contains the transcript and citations.

**Acceptance Scenarios**:

1. **Given** a user is in a private room with a Ghost, **When** the user starts a voice call, **Then** the Ghost joins the call and is audible to the user.
2. **Given** an active voice call with a Ghost, **When** the user speaks a question, **Then** the Ghost responds in voice with an answer grounded in its memory.
3. **Given** an active voice call, **When** the Ghost responds, **Then** a text transcript of the Ghost's response appears in a text thread in the same room, including citation markers and source references.
4. **Given** an active voice call, **When** the user or Ghost ends the call, **Then** the voice session terminates cleanly and the full transcript remains in the text thread.
5. **Given** an active voice call, **When** the Ghost's memory service is temporarily unavailable, **Then** the Ghost communicates (in voice) that its memory is temporarily unavailable rather than fabricating an answer.

---

### User Story 4 - Multi-Agent Voice Discussion (Priority: P4)

A user starts a voice call in a discussion room with multiple Ghosts. The Ghosts engage in a spoken "agentic podcast" by requesting speaking turns through floor control; only the floor holder is unmuted. The user can listen, interject verbally at any time, and moderate. A text thread captures the full transcript with citations from all participants.

**Why this priority**: This is the most advanced and differentiated experience Bibliotalk offers — a live, spoken conversation between historical figures. It depends on both multi-agent text discussions (P2) and single-Ghost voice calls (P3) being complete.

**Independent Test**: Can be tested by starting a voice call in a room with two Ghosts and a topic, then verifying that only one Ghost emits audio at once, user barge-in stops Ghost speech immediately, and transcript entries with citations are preserved per speaker.

**Acceptance Scenarios**:

1. **Given** a user starts a voice call in a discussion room with multiple Ghosts, **When** the call begins, **Then** each Ghost joins the call as a distinct voice participant.
2. **Given** an active multi-agent voice discussion, **When** one Ghost is speaking, **Then** other Ghost outputs are muted by floor control.
3. **Given** an active multi-agent voice discussion, **When** the user starts speaking, **Then** current Ghost audio is canceled/muted immediately and user speech takes the floor.
4. **Given** an active multi-agent voice discussion, **When** any Ghost speaks, **Then** the text thread is updated with that Ghost's transcript and citations.
5. **Given** a multi-agent voice discussion, **When** the user directly addresses a Ghost by mention or name, **Then** that Ghost is strongly preferred for the next floor grant after user end-of-utterance.
6. **Given** a multi-agent voice discussion, **When** the configured number of turns is reached or the user stops the discussion, **Then** all Ghost voice participation ceases and the text transcript remains available.

---

### Edge Cases

- What happens when a Ghost's memory service is unavailable during a conversation? The Ghost MUST explicitly state that its memory is temporarily unavailable rather than hallucinating or going silent.
- What happens when a user sends a message in a room where multiple Ghosts are present but no discussion has been started? Only the Ghost that is directly mentioned or addressed responds. If no Ghost is mentioned, no Ghost responds.
- What happens when a voice call drops unexpectedly (network failure)? The system MUST log the disconnection, preserve whatever transcript has been captured so far, and not leave orphaned sessions.
- What happens when two Ghosts in a multi-agent discussion share the same source material (e.g., both have ingested the same podcast)? Each Ghost cites only from its own memory space; overlapping source material is expected and valid.
- What happens when the voice backend (speech-to-speech service) fails mid-call? The system MUST notify the user (via text in the room) that voice capability is temporarily unavailable and terminate the call gracefully.
- What happens when a user tries to start a voice call in a profile room? The system MUST reject the request — profile rooms are read-only and do not support interactive conversations.
- What happens when a Ghost receives a message in a language different from its primary language? The Ghost responds using whatever evidence it has in its memory, regardless of language. No automatic translation is applied.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST receive messages from the chat platform and route them to the appropriate Ghost based on room membership and addressing (direct mention or DM).
- **FR-002**: Each Ghost MUST have a distinct persona (name, biography, behavioral instructions) that governs its conversational style and character.
- **FR-003**: Before generating any response, a Ghost MUST search its personal memory for evidence relevant to the user's message.
- **FR-004**: Every factual claim in a Ghost's response MUST include an inline citation marker (e.g., superscript number) linking to a specific source passage.
- **FR-005**: System MUST validate all citations before delivering a Ghost's response — citations referencing non-existent sources or mismatched quotes MUST be stripped.
- **FR-006**: When a Ghost has no relevant evidence for a query, it MUST explicitly acknowledge the gap rather than fabricating content.
- **FR-007**: System MUST enforce that Ghosts never generate responses in profile rooms (public, read-only rooms designated for verbatim ingested content), enforced via Matrix room permissions.
  - Implementation note: in addition to permissions, `agents_service` must treat rooms listed in `profile_rooms` as “no response” rooms.
- **FR-008**: System MUST run a per-room Discussion Controller that enforces one active speaker at a time for multi-agent discussions, with configurable turn limits and user interjection.
- **FR-009**: In multi-agent discussions, each Ghost MUST cite only from its own memory — never from another Ghost's memory.
- **FR-010**: System MUST support real-time voice conversations between a user and a Ghost, with the Ghost responding in speech grounded in its memory.
- **FR-011**: During voice calls, the system MUST produce a text transcript with citations in a parallel text thread in the same room.
- **FR-012**: System MUST support multi-agent voice discussions (agentic podcasts) using floor-gated audio output so only the floor holder emits Ghost audio.
- **FR-013**: System MUST rate-limit Ghost responses (max one response per 5 seconds per room) to prevent spam loops in multi-Ghost rooms.
- **FR-014**: System MUST store conversation transcripts (both text and voice) for audit and future reference.
- **FR-015**: System MUST support swapping between different voice engines without changing the user-facing call experience.
- **FR-016**: System MUST allow per-Ghost configuration of the underlying language model used for generating responses.
- **FR-017**: Ghost runners MUST request permission to speak via `REQUEST_FLOOR(force: bool)` and MUST NOT post directly to Matrix rooms.
- **FR-018**: While a user is speaking, Ghost `REQUEST_FLOOR` intents MUST be accepted only with `force=false`; user speech MUST be non-preemptible.
- **FR-019**: `REQUEST_FLOOR(force=true)` MAY preempt an active Ghost speaker only when controller thresholds and rate limits pass.
- **FR-020**: Scheduler MUST boost selection priority for Ghosts explicitly addressed by the latest user utterance (mention/name), with topic coherence included in relevance scoring.

### Key Entities

- **Ghost**: An AI digital twin of a person (figure or user). Has a unique persona, its own memory space, and can participate in text and voice conversations. Each Ghost operates independently and cites only from its own sources.
- **Agent Configuration**: The settings that define a Ghost — persona instructions, language model selection, memory service connection details, and active/inactive status.
- **Memory**: The collection of ingested source material (books, podcast transcripts, video transcripts) associated with a specific Ghost. Searched during every response generation to ground claims.
- **Citation**: A structured reference linking a specific claim in a Ghost's response to a verifiable passage in its memory. Contains the source title, URL, and verbatim quote.
- **Discussion**: A structured multi-agent conversation with a topic, participant Ghosts, floor-control state, and configurable turn limits. Can operate in text or voice mode.
- **Voice Session**: A real-time speech connection between a user and one or more Ghosts. Produces audio output and a parallel text transcript with citations.
- **Chat History**: A record of all messages exchanged in conversations (text and voice transcripts), including associated citations, for audit and potential future memorization.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users receive a grounded, cited response from a Ghost within 5 seconds of sending a text message (measured from message delivery to response delivery in the chat room).
- **SC-002**: 100% of citations in delivered Ghost responses are verifiable — each cited quote is a substring of the referenced source passage. No unvalidated citations reach the user.
- **SC-003**: Ghosts generate zero responses in profile rooms under all conditions (100% enforcement via Matrix room permissions).
- **SC-004**: In multi-agent discussions, each Ghost speaks only from its own memory. Zero cross-Ghost citation leaks across all discussion sessions.
- **SC-005**: Voice call audio latency from end of user speech to start of Ghost speech is under 3 seconds (measured end-to-end including memory search).
- **SC-006**: 100% of voice call turns produce a corresponding text transcript entry with citations in the parallel text thread.
- **SC-007**: In multi-agent voice discussions, simultaneous Ghost speech overlap longer than 250 ms occurs in 0% of turns (floor-control enforcement).
- **SC-008**: System handles at least 50 concurrent active Ghost conversations (text or voice) without degradation in response time.
- **SC-009**: When a Ghost's memory service is unavailable, the Ghost acknowledges the gap in 100% of cases — zero hallucinated responses during memory outages.
- **SC-010**: Swapping between voice engines for a Ghost requires only a configuration change, with zero modifications to the call setup or user experience.

### Assumptions

- For production, the chat platform (Matrix/Synapse) and appservice registration are deployed and operational before this feature is used.
- For local end-to-end development, the repo provides `deploy/local/*` assets to run Synapse + Element Web, and the appservice registration is generated locally.
- For production, the relational database schema for agents, agent configurations, and related tables is provisioned (blueprint target: Postgres, accessed via SQLAlchemy).
- For local end-to-end development, the logical schema is provisioned in SQLite (via SQLAlchemy ORM metadata / migrations as needed).
- Content ingestion pipelines (Podwise, Gutenberg, YouTube) are a separate feature — this specification assumes source material already exists in each Ghost's memory when the agent service processes a conversation.
- The voice sidecar (audio bridge between the chat platform's voice protocol and the agent service) is treated as part of this feature's scope, since voice chat capability is explicitly requested.
- Unencrypted voice calls are acceptable for MVP. End-to-end encrypted voice is deferred.
- The system operates on a single homeserver instance (no federation).
