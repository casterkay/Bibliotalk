# Contract: Discussion Floor Control

**Service**: Per-room Discussion Controller in `agents_service`
**Scope**: Multi-agent text and voice discussions (Matrix-native)

## Core Principles

1. Exactly one active speaker per room at any time.
2. User speech/message has absolute preemption priority.
3. Ghost runners do not post directly to Matrix; they request floor.
4. Every in-flight agent generation is cancellable.

## Floor States

```text
IDLE
USER_SPEAKING(user_id)
AGENT_SPEAKING(agent_id, generation_id)
```

State transitions:
- `IDLE -> USER_SPEAKING` on user VAD start or user text event
- `IDLE -> AGENT_SPEAKING` on grant of queued request
- `AGENT_SPEAKING -> USER_SPEAKING` on user barge-in (cancel required)
- `AGENT_SPEAKING -> IDLE` on completion/timeout/cancel
- `USER_SPEAKING -> IDLE` on end-of-utterance

## `REQUEST_FLOOR`

Ghost runners submit at most one outstanding request per room.

```json
{
  "type": "REQUEST_FLOOR",
  "room_id": "!room:server",
  "agent_id": "@btghost_confucius:bibliotalk.space",
  "force": false,
  "reason": "Direct answer to user question",
  "urgency": 0.7,
  "relevance": 0.9,
  "estimate_ms": 12000,
  "max_tokens": 500
}
```

Rules:
- `force=true` may preempt only an active `AGENT_SPEAKING` holder.
- While `USER_SPEAKING`, agents may send `REQUEST_FLOOR` but must use
  `force=false`.
- Controller can clamp `estimate_ms` and `max_tokens`.
- Controller enforces cooldowns and force-rate limits.

## Scheduler Contract

When floor is available, choose highest score subject to hard
constraints.

Hard constraints:
- Never preempt user speech.
- One active speaker max.
- Per-agent cooldown and max continuous speak window.

Score function:
`score = w_m * mention_boost + w_r * relevance + w_u * urgency + w_f * fairness + w_e * evidence`

Where:
- `mention_boost`: latest user utterance directly addresses that agent
- `relevance`: fit to current conversational context (includes topic coherence)
- `evidence`: grounded retrieval readiness for likely response

## Cancellation Contract

Each granted turn has `generation_id` and cancellation token.

Controller must support:
- `CANCEL(generation_id, reason)` on user barge-in, force-preemption, stop
- Immediate stop for text token streaming and voice TTS output
- Best-effort acknowledgement in logs/metrics

## Streaming Contract

Text:
1. Post placeholder message as speaking Ghost.
2. Stream text via Matrix edits.
3. Finalize message.
4. Attach validated citations inline or in follow-up thread event.

Voice:
1. Only floor holder is unmuted for TTS emission.
2. User VAD start mutes Ghost audio and triggers cancellation.
3. Transcript and citations are posted to room thread in near real time.

## Determinism and Audit

- Controller records floor decisions and preemption events to
  `chat_history`/logs with room_id, speaker_id, generation_id, reason.
- Tie-break rules are deterministic (e.g., oldest request wins on equal score).
