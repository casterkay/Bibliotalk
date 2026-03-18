API endpoints:
- GET /health
- GET /memories/{memory_id} -> HTML (corresponds to a single evidence including a single search result in EverMemOS (MemCell) and source excerpt)
- GET /v1/memories -> JSON (provide request param `id` - MemCell, or `source_id` -
equivalent to `group_id` in EverMemOS ({agent-slug}:{platform}:{external_id}) - full
video, ebook, podcast episode, etc.; always returns a list of memories, even with `id` parameter)
- POST /v1/ingest -> triggers manual ingest of a single source (video, ebook, etc.)
- POST /v1/ingest-batch -> triggers manual ingest of a source collection (single URL
like youtube playlist or blog sitemap.xml, or a list of URLs) into an agent's memory
- POST /v1/subscribe -> subscribe agent memory to new RSS feed (including youtube
channel RSS or podcast RSS)
- GET /v1/search -> EverMemOS search joined with corresponding source content (EMOS
only returns summary)

Note that a memory cell contains a sequence of chunks ingested into the memory store.
We only retrieve individual cells instead of chunks. How to know what chunks belong to
a single cell? First we keep track of the timestamp of each chunk (mock timestamps for
ebooks), then we ingest all chunks belonging to a single source into EverMemOS, then
we fetch all memory cells belonging to the its `group_id` from EMOS, each of which
contains a timestamp, and finally we can split the chunk sequence by cell timestamps
to obtain the chunks belonging to each cell.

In the DB schema, only the "agent" term is used. Actually, "agents" have two kinds: "figure" and "user", so agent and figure are concepts at different levels. "figure" means public figures, including historical figures, while "user" means app users. However, in the user-facing aspect, "spirit" is a synonym of Bibliotalk "agent" emphasizing its digital memory of human individuals. Thus there are spirits of public figures as well as spirits of app users.
