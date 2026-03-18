# Feature Specification: EverMemOS Content Ingestion

**Feature Branch**: `[002-evermemos-content-ingest]`
**Created**: 2026-03-01
**Status**: Draft
**Input**: User description: "Create a standalone ingestion package to load curated content into EverMemOS (per BLUEPRINT.md and ROSTER.md), without any interactive web crawling."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ingest A Single Source For A Spirit (Priority: P1)

As a curator or operator, I can ingest a single content source (for example: a book, an essay, or a time-coded transcript) into EverMemOS for a specific agent, so that the Spirit can later answer questions grounded in that material with verifiable citations.

**Why this priority**: This is the smallest end-to-end unit of value: one real source becomes usable evidence for grounded conversation.

**Independent Test**: Can be fully tested by ingesting one source and verifying (a) content is retrievable from EverMemOS for that agent and (b) each citation can be traced back to an exact verbatim segment with correct source attribution.

**Acceptance Scenarios**:

1. **Given** valid EverMemOS credentials and a single source with title and canonical link, **When** ingestion runs, **Then** the source’s content is stored in EverMemOS as a set of ordered segments grouped under that source and ingestion reports success.
2. **Given** a source whose content cannot be parsed or segmented, **When** ingestion runs, **Then** no partial or misleading ingestion result is reported as “successful”, and the failure includes a human-actionable reason.
3. **Given** a source that cannot be ingested without interactive browsing or dynamic page interaction, **When** ingestion runs, **Then** ingestion fails for that source with an actionable message and does not store partial content.
4. **Given** invalid EverMemOS credentials, **When** ingestion runs, **Then** ingestion fails safely and the reported error contains no secrets.

---

### User Story 2 - Safe Re-Run Without Duplicates (Priority: P2)

As an operator, I can re-run ingestion for a previously ingested source to either (a) confirm it is already ingested or (b) apply updates, without creating duplicate segments or breaking citation traceability.

**Why this priority**: Ingestion will be run repeatedly (retries, scheduled refreshes, updated sources). Duplicates degrade retrieval quality and citation trust.

**Independent Test**: Can be fully tested by ingesting the same source twice and confirming that EverMemOS content and citation traceability remain stable (no duplicate segments; updates only when content changes).

**Acceptance Scenarios**:

1. **Given** a source already ingested with unchanged content, **When** ingestion runs again, **Then** it completes without creating duplicate stored segments and reports “no changes” (or equivalent).
2. **Given** a source already ingested but with updated content, **When** ingestion runs again, **Then** only the changed portions are reflected in storage and the report clearly indicates what changed.

---

### User Story 3 - Batch Ingest From A Curated Roster (Priority: P3)

As a curator, I can ingest a curated roster of sources for multiple agents (for example: a reading list plus public talks/transcripts) in a single batch run, and receive a clear per-source success/failure report.

**Why this priority**: The system’s value grows with breadth of high-quality sources. Batch ingestion reduces operational overhead and makes it feasible to ingest a roster like the one maintained for Bibliotalk figures.

**Independent Test**: Can be fully tested by running ingestion on a small roster (3–5 sources) and validating that each item either ingests successfully or fails with actionable errors, without blocking the whole batch.

**Acceptance Scenarios**:

1. **Given** a roster containing multiple sources across one or more figures, **When** batch ingestion runs, **Then** each source produces an independent status outcome and the overall run produces a consolidated report.

---

### Edge Cases

- What happens when EverMemOS is temporarily unavailable during ingestion (network outage or service error)?
- What happens when credentials are invalid, expired, or not authorized for the target agent?
- How does the system handle extremely large sources (very long books, multi-hour transcripts)?
- How does the system handle content with mixed languages or unusual encodings?
- What happens when a source URL exists but content retrieval requires interactive browsing, authentication, or dynamic page interaction?
- How does the system handle partial failures in a batch (one source fails mid-run)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support ingesting content provided directly by an operator (for example: pasted text, uploaded documents, or exported transcripts).
- **FR-002**: System MUST support ingesting time-coded transcripts (when available) while preserving enough “location” context to produce precise citations (for example: timestamps or section markers).
- **FR-003**: System MUST allow operators to associate each ingestion with (a) the agent whose memory is being populated and (b) the source identity (title and canonical link).
- **FR-004**: System MUST segment each source into ordered, citation-friendly chunks and store those chunks in EverMemOS under a single source grouping so retrieval can use cross-segment context.
- **FR-005**: System MUST attach source-level metadata in EverMemOS sufficient to support later citation rendering (at minimum: source title and canonical link; optionally: author/publisher/date when provided).
- **FR-006**: System MUST provide an ingestion report for each run that includes per-source status, counts of stored segments, and error details where relevant.
- **FR-007**: System MUST be safe to re-run for the same source without creating duplicate stored content, and MUST clearly report whether content was newly added, unchanged, or updated.
- **FR-008**: System MUST support batch ingestion of multiple sources and MUST continue processing remaining sources when individual sources fail.
- **FR-009**: System MUST NOT use interactive web browsing or automated page interaction to obtain content; if a source cannot be ingested without such interaction, the system MUST fail that source with an explicit, actionable message. Non-interactive HTTP fetching + static extraction (for example, `trafilatura`) is allowed.
- **FR-010**: System MUST protect secrets and sensitive configuration: it MUST NOT write credentials into logs, error messages, or ingestion reports.
- **FR-011**: System MUST preserve verbatim ingested text such that later citation verification can confirm that cited quotes are exact substrings of the original ingested segments.

### Acceptance Coverage

- **FR-001–FR-006, FR-009–FR-011**: Demonstrated by User Story 1 acceptance scenarios and the independent citation-verification test.
- **FR-007**: Demonstrated by User Story 2 acceptance scenarios.
- **FR-008**: Demonstrated by User Story 3 acceptance scenario.

### Key Entities *(include if feature involves data)*

- **Agent**: The identity whose EverMemOS memory is being populated; used to scope retrieval and grounding.
- **Source**: A single upstream content item (for example: one book, one talk transcript, one podcast episode transcript) with canonical attribution metadata.
- **Segment**: A verbatim chunk of a source with ordering and optional location markers (timestamps/section markers) used for citations.
- **Ingestion Run**: One execution attempt that processes one or more sources and yields a consolidated report with per-source outcomes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a batch of 50 curated sources, at least 95% complete ingestion successfully on the first run (no manual intervention beyond providing credentials and source content/metadata).
- **SC-002**: Re-running ingestion for an unchanged batch of 50 previously ingested sources results in 0 duplicate stored segments and completes with a “no changes” outcome for at least 95% of sources.
- **SC-003**: In a validation set of 100 cited claims generated by Spirits from ingested material, at least 90% of citations resolve to a verifiable verbatim segment with correct source attribution (title + canonical link + location when available).
- **SC-004**: For failed sources, operators can determine the cause and next corrective action from the ingestion report in under 5 minutes per failed source.

## Scope

This feature covers ingesting curated, consented content into EverMemOS to support grounded Spirit conversations with citations. It focuses on transforming operator-provided content into well-attributed, deduplicated, citation-friendly stored memory.

## Out of Scope

- Automated interactive browsing, account login flows, or dynamic page interaction to obtain content.
- Social media ingestion and general-purpose, unbounded web crawling.
- Billing, token metering, or user-facing pricing.
- Spirit response generation, retrieval prompting strategies, or citation rendering in chat clients (only ingestion prerequisites).

## Assumptions

- Operators can obtain the content artifacts to ingest (documents or transcripts) through lawful and appropriate means and provide canonical attribution metadata.
- EverMemOS supports storing segmented content under a source grouping and supports later retrieval for grounded answering.
- The ingestion component will be used by other services or operators; it does not need to be a full end-user product UI.

## Dependencies

- Availability and access to EverMemOS for the relevant agent (credentials and authorization).
- Access to canonical source metadata (at minimum: title and canonical link).
