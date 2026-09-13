# Where the reference library is stored — SQLite, compared

13 September 2026. The question: the reference library keeps its passages,
keyword index and vectors in one SQLite file (`data/library/index.sqlite`,
built by `workbench/library.py`). Should it use a vector database instead?

**Short answer: SQLite is the better choice for this system today.** It meets
every requirement below with nothing new to install, run or secure. The limits
are real but far away, and the upgrade path is known.

---

## 1. What the library has to do

1. **Run on one air-gapped machine** — no network, ideally no extra server.
2. **Keyword (BM25) and meaning (vector) search together.** Codes like
   "OISD-STD-118 Cl. 6.2" are found by keywords; vectors miss them.
3. **Keep each passage's document, section, page and box**, so every answer
   cites the exact place it came from.
4. **Match identifiers exactly and follow references** ("under SOP-INSP-001
   section 2").
5. **A licence MRPL can use.**
6. **Few moving parts** to copy into the sealed build and to audit.

## 2. The options

| Option | Runs as | BM25 + vectors, offline | Keeps page and box | Licence | Extra to install | Verdict |
|---|---|---|---|---|---|---|
| **Our SQLite index** (FTS5 + vectors in a table) | Inside our process; one file | **Yes** — BM25 is built into SQLite (3.45.3 here); cosine in numpy | Yes, our own columns | Public domain | **Nothing** | **Chosen** |
| LanceDB (AnythingLLM's built-in store) | Embedded library | Yes — full-text search (BM25) and hybrid search with rerankers | Yes, as columns | Apache-2.0 | `lancedb` | Strong alternative |
| Chroma | Embedded or server | **No, not locally** — its BM25/sparse search reported "not enabled in local" (Jan 2026); vectors only | Yes | Apache-2.0 | `chromadb` | Out |
| Qdrant | A server, or local mode in its Python client | Yes — BM25 as sparse vectors (FastEmbed model files to copy in) | Yes | Apache-2.0 | Server or client + FastEmbed | For a large, shared deployment |
| pgvector (PostgreSQL) | A database server | Yes — Postgres full-text search + vectors | Yes | PostgreSQL (BSD-style) | A Postgres server to run and secure | Out for one workstation |
| FAISS | Library | **No** — vectors only; metadata filtering awkward | No (kept elsewhere) | MIT | `faiss` | Out |
| sqlite-vec | SQLite extension | Adds a vector index to the same file; BM25 stays FTS5 | Yes | Apache-2.0 | One extension file | **The upgrade path** |

About AnythingLLM: its documentation describes document chat as similarity
search, with optional reranking on LanceDB. Keyword search is a feature of
LanceDB itself, not something AnythingLLM's document chat describes using.
Either way, citations with page and box, identifier matching and reference
following would still be our code.

## 3. Measured on this machine (RTX 4070, 32 GB RAM)

| | Result |
|---|---|
| Today's library | 12 documents, 334 passages; right passage in the top 5 for **22 / 22** questions; every document for **4 / 4** multi-document questions |
| Time per search | ~260 ms, almost all of it the embedding model reading the question |
| Vector search, in memory | 0.05 ms at 334 passages · 0.3 ms at 10,000 · **6 ms at 100,000** · 32 ms at 500,000 (1.5 GB of vectors) |
| Reading vectors from the file on every question | ~500 ms at 100,000 — **fixed**: loaded once, kept until the index file changes |

## 4. Why SQLite wins here

- **Nothing to run or secure.** No database server, no port, no service account — one less thing the network proof (R6) has to cover.
- **One file** to copy into the sealed build, hash, back up and audit.
- **Citations are ours.** Page, box and section are plain columns next to the text, the same provenance the Reader gives every inspection value.
- **Both kinds of search in the same place**, with the fusion, identifier boost and reference following in about 100 lines we can show and explain.
- **No new dependency**: SQLite ships with Python; numpy was already installed.

## 5. Honest limits, and when to switch

| Limit | When it matters | Then |
|---|---|---|
| Vector search is brute force | Beyond a few hundred thousand passages (32 ms at 500,000 is still fine) | **sqlite-vec** — same file, same code shape; or LanceDB |
| One workstation, one writer | A plant-wide service with many concurrent users | Qdrant or pgvector as a server |
| A rebuild replaces the whole index | A library changing all day | Incremental updates by document hash |

## 6. What we say to judges

"The library is one file on the machine. Keyword and meaning search run in
SQLite, and every passage keeps the page it came from, so every answer points
to its source. There is no database server to secure and nothing that can call
out. It is measured fast to half a million passages, and sqlite-vec is the
drop-in when MRPL's library outgrows that."

---

## Sources

- AnythingLLM vector databases (LanceDB default; PGVector, Chroma, Qdrant, Milvus and others): [docs](https://docs.useanything.com/features/vector-databases), [LanceDB setup](https://docs.anythingllm.com/setup/vector-database-configuration/local/lancedb)
- AnythingLLM search and reranking: [Using documents](https://docs.anythingllm.com/chatting-with-documents/introduction), [DeepWiki: similarity search and reranking](https://deepwiki.com/Mintplex-Labs/anything-llm/6.4-similarity-search-and-reranking)
- LanceDB full-text and hybrid search: [docs](https://docs.lancedb.com/search/full-text-search)
- Chroma sparse vectors: [announcement](https://www.trychroma.com/project/sparse-vector-search); local limitation: [issue #6185](https://github.com/chroma-core/chroma/issues/6185)
- Qdrant hybrid search and BM25: [article](https://qdrant.tech/articles/hybrid-search/), [sparse retrieval](https://qdrant.tech/course/essentials/day-3/sparse-retrieval-demo/)
- pgvector: [repository](https://github.com/pgvector/pgvector) (licence file: PostgreSQL); FAISS filtering: [discussion #4144](https://github.com/facebookresearch/faiss/discussions/4144)
- sqlite-vec: [repository](https://github.com/asg017/sqlite-vec)
- Licences: each project's GitHub record, read 2026-09-13; SQLite: [public domain](https://sqlite.org/copyright.html)
- Timings: measured on the bench, 2026-09-13 (random 768-dimension vectors; `library.search` on the real index)
