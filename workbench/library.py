"""The reference library: search over procedures, memos and public documents, with citations.

    .venv\\Scripts\\python -m workbench.library build
    .venv\\Scripts\\python -m workbench.library search "which procedure applies OISD-STD-118 Cl. 6.2"

The knowledge base's second store (docs/WHOLE_PICTURE.md section 7b). It supplies
wording, context and citations -- never a number that goes into a deliverable;
numbers come from the evidence store.

How a document gets in:

    PDF -> the Reader (workbench/pagesource.py, the same code that reads the
    inspection reports) -> lines -> page furniture and footnotes set apart ->
    sections split at numbered bold headings -> chunks of bounded length, each
    keeping its document, section, pages and box -> SQLite full-text index +
    vectors from the embedding model the Router chooses

How a question gets answered (search only -- the Librarian agent writes the
answer, and has to cite what this returns):

    keyword search (SQLite FTS5, BM25)  --\\
    vector search (cosine)              ----> reciprocal-rank fusion -> ranked chunks
    exact identifier match              --/        -> + sections those chunks refer to

The identifier match is there because embeddings are worst at exactly the
tokens that matter most here: "OISD-STD-118 Cl. 6.2" and "SOP-INSP-004" mean
nothing to a vector model, and everything to an engineer.

Nothing about particular documents is in this file. Which sources, the layout
thresholds, identifier and reference patterns: workbench/library.yaml. Which
embedding model, its server and its task prefixes: workbench/models.yaml,
through the Router.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import re
import sqlite3
import statistics
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
import yaml

from workbench import router
from workbench.pagesource import TEXT_LAYER, Page, open_document, sha256_file

ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path(__file__).resolve().parent / "library.yaml"


@lru_cache(maxsize=None)
def config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def index_path() -> Path:
    return ROOT / config()["index"]


def sources() -> tuple[list[dict], list[str]]:
    """What the library holds -- the explicit list in library.yaml -- and any listed file that is missing."""
    found, missing = [], []
    for entry in config()["sources"]:
        if "glob" in entry:
            found += [{"doc_id": f.stem, "file": f, "origin": entry["origin"]}
                      for f in sorted(ROOT.glob(entry["glob"]))]
        elif (ROOT / entry["file"]).exists():
            f = ROOT / entry["file"]
            found.append({"doc_id": entry.get("doc_id", f.stem), "file": f, "origin": entry["origin"]})
        else:
            missing.append(entry["file"])
    return found, missing


# --- reading a document into lines -------------------------------------------------

@dataclass
class Line:
    text: str
    page: int
    bbox: tuple[float, float, float, float]
    height: float             # the tallest piece on the row -- roughly the type size
    y_frac: float             # the row's centre, as a fraction of the page height
    bold: bool | None = None  # from the PDF's font; None when the page was read by OCR


def page_lines(page: Page) -> list[Line]:
    """Pieces of text on the same row, joined left to right.

    The Reader returns text in pieces: a table row arrives as three cells, a
    justified line as two runs, a small-caps footer as a dozen fragments.
    """
    lay = config()["layout"]
    items = sorted(page.items, key=lambda i: ((i.bbox[1] + i.bbox[3]) / 2, i.bbox[0]))
    rows: list[list] = []
    for it in items:
        cy = (it.bbox[1] + it.bbox[3]) / 2
        if rows and abs(cy - rows[-1][0]) <= max(lay["row_join_px"], lay["row_join_share"] * (it.bbox[3] - it.bbox[1])):
            rows[-1][1].append(it)
        else:
            rows.append([cy, [it]])
    lines = []
    for cy, row in rows:
        row.sort(key=lambda i: i.bbox[0])
        text = re.sub(r"\s+", " ", " ".join(i.text for i in row)).strip()
        if text:
            lines.append(Line(text, page.number,
                              (min(i.bbox[0] for i in row), min(i.bbox[1] for i in row),
                               max(i.bbox[2] for i in row), max(i.bbox[3] for i in row)),
                              max(i.bbox[3] - i.bbox[1] for i in row), cy / page.height))
    return lines


BARE_NUMBER = re.compile(r"[\d\s]+")


def _shape(text: str, doc_id: str = "") -> str:
    """A line with its digits, spacing and own document id removed: page 30 of
    one document and page 1 of another are the same furniture."""
    if doc_id:
        text = re.sub(re.escape(doc_id), "\0", text, flags=re.I)
    return re.sub(r"[\d\s]", "", text).lower()


def body_height(pages_lines: list[list[Line]]) -> float:
    """The usual height of a line of running text in this document."""
    n = config()["layout"]["body_line_min_chars"]
    heights = [l.height for lines in pages_lines for l in lines if len(l.text) >= n]
    return statistics.median(heights) if heights else 0.0


def strip_furniture(pages_lines: list[list[Line]], doc_id: str, library_shapes: Counter,
                    n_docs: int) -> list[list[Line]]:
    """Remove, page by page, what repeats in the margins of most pages or most documents.

    Only margins: every procedure has a "1. Purpose and scope" heading and an
    "Issued" line, and those repeat across documents as much as the footer does.
    Bare numbers are kept here -- they may be footnote marks (split_footnotes).
    """
    lay = config()["layout"]
    share, least = lay["repeat_share"], lay["repeat_min_count"]
    n = len(pages_lines)
    per_page = Counter(s for lines in pages_lines for s in {_shape(l.text, doc_id) for l in lines})
    kept = []
    for lines in pages_lines:
        page = []
        for line in lines:
            shape = _shape(line.text, doc_id)
            in_margin = line.y_frac < lay["margin"] or line.y_frac > 1 - lay["margin"]
            repeats = (n >= least and per_page[shape] >= share * n) or \
                      (n_docs >= least and library_shapes[shape] >= share * n_docs)
            if shape and in_margin and repeats:
                continue
            page.append(line)
        kept.append(page)
    return kept


def split_footnotes(lines: list[Line], body_h: float) -> tuple[list[Line], list[Line]]:
    """A page's running text, and its footnotes.

    A footnote block starts at a small bare number -- the mark -- after which
    nothing on the page is set at body size. A superscript mark inside the text
    is followed by more running text, so it never starts a block. Left in place,
    footnotes cut sections in half, and a numbered list inside a footnote ("3.
    Hazardous material or fire incident...") passes for a heading.
    """
    lay = config()["layout"]
    if body_h:
        for i, line in enumerate(lines[:-1]):
            if BARE_NUMBER.fullmatch(line.text) and line.height < lay["footnote_mark"] * body_h \
                    and all(l.height < lay["footnote_text"] * body_h for l in lines[i + 1:]):
                return lines[:i], lines[i:]
    return lines, []


def mark_bold(file: Path, pages: list[Page], pages_lines: list[list[Line]]) -> None:
    """Set Line.bold from the font of each line's first character, in the PDF itself.

    Type size cannot tell a heading from running text: the CSB's text layer
    reports every character at size 1.0 (the scaling is in its text matrix), and
    a line's box height depends on its letters. Bold can: bold headings in both
    the procedures and the CSB, while the CSB's contents pages, numbered findings
    and footnote lists are regular. Read here rather than in the Reader, which
    the inspection pipeline shares. Pages read by OCR have no fonts, and stay None.
    """
    if Path(file).suffix.lower() != ".pdf":
        return
    lay = config()["layout"]
    pdf = pdfium.PdfDocument(str(file))
    name = (ctypes.c_char * 128)()
    flags = ctypes.c_int()
    tol = lay["probe_tolerance_pt"]
    for page, lines in zip(pages, pages_lines):
        if page.read_by != TEXT_LAYER:
            continue
        scale = page.dpi / 72
        pp = pdf[page.number - 1]
        tp, height_pt = pp.get_textpage(), pp.get_height()
        for line in lines:
            x = line.bbox[0] / scale + lay["probe_offset_pt"]
            y = height_pt - (line.bbox[1] + line.bbox[3]) / 2 / scale
            j = pdfium_c.FPDFText_GetCharIndexAtPos(tp.raw, x, y, tol, tol)
            if j < 0:
                continue
            pdfium_c.FPDFText_GetFontInfo(tp.raw, j, name, len(name), flags)
            line.bold = ("bold" in name.value.decode("latin-1").lower()
                         or pdfium_c.FPDFText_GetFontWeight(tp.raw, j) >= lay["bold_min_weight"])


def _heading_type(line: Line, body_h: float) -> bool:
    if line.bold is not None:
        return line.bold
    return line.height >= config()["layout"]["heading_scale"] * body_h


def sections(lines: list[Line], body_h: float) -> list[dict]:
    """Split at numbered headings ("3. The half-life rule", "4.1 Sulfidation Corrosion").

    A heading is a numbered line in bold (mark_bold): the CSB's numbered
    findings, its contents pages and the lists inside its footnotes are regular
    type, and are not headings. Text before the first heading (a document's
    title block, a memo's To/From lines) is section "0".
    """
    lay = config()["layout"]
    heading, leader = re.compile(lay["section_heading"]), re.compile(lay["dot_leader"])
    out = [{"section": "0", "heading": "", "lines": []}]
    for line in lines:
        if not _shape(line.text):                                  # page numbers, superscript marks
            continue
        m = heading.match(line.text)
        if m and not leader.search(line.text) and len(line.text) <= lay["heading_max_chars"] \
                and _heading_type(line, body_h):
            out.append({"section": m.group(1), "heading": m.group(2).strip(), "lines": []})
        else:
            out[-1]["lines"].append(line)
    return [s for s in out if s["lines"] or s["heading"]]


def footnote_sections(notes_per_page: list[list[Line]]) -> list[dict]:
    """One section per page of footnotes, each note keeping its number ("10 Based on ...")."""
    out = []
    for lines in notes_per_page:
        joined, mark = [], None
        for line in lines:
            if BARE_NUMBER.fullmatch(line.text):
                mark = line.text.strip()
                continue
            if mark:
                line = Line(f"{mark} {line.text}", line.page, line.bbox, line.height, line.y_frac, line.bold)
                mark = None
            joined.append(line)
        if joined:
            out.append({"section": "footnotes", "heading": f"Footnotes, page {joined[0].page}", "lines": joined})
    return out


def chunks_of(section: dict) -> list[list[Line]]:
    """A section in pieces of at most chunking.max_chars, split between lines, never mid-line."""
    limit = config()["chunking"]["max_chars"]
    pieces, current, size = [], [], 0
    for line in section["lines"]:
        if current and size + len(line.text) > limit:
            pieces.append(current)
            current, size = [], 0
        current.append(line)
        size += len(line.text) + 1
    if current or not pieces:
        pieces.append(current)
    return pieces


# --- the index ---------------------------------------------------------------------

SCHEMA = """
create table if not exists documents (
    doc_id text primary key, title text, origin text, file text, sha256 text, pages integer
);
create table if not exists chunks (
    id integer primary key, doc_id text, section text, heading text, part integer,
    page_first integer, page_last integer, bbox text, text text
);
create virtual table if not exists chunks_fts using fts5(heading, text, content='chunks', content_rowid='id');
create table if not exists vectors (chunk_id integer primary key, vector blob);
create table if not exists meta (key text primary key, value text);
"""


def embed(texts: list[str], model: str, role: str) -> np.ndarray:
    """Unit-length vectors from `model`, on the server models.yaml names for it.

    `role` is "document" (what is stored) or "query" (a question). Some models
    need a task prefix for each -- nomic-embed-text does -- and models.yaml
    records it with the model.
    """
    registry, _ = router.load_registry()
    prefix = (registry["models"][model].get("prefixes") or {}).get(role, "")
    url = router.endpoint(model, registry) + "/api/embed"
    out = []
    for i in range(0, len(texts), 32):
        r = httpx.post(url, timeout=300, json={"model": model, "input": [prefix + t for t in texts[i:i + 32]]})
        r.raise_for_status()
        out.extend(r.json()["embeddings"])
    v = np.asarray(out, dtype=np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)


def build(path: Path | None = None) -> dict:
    """Read every source through the Reader and index it from scratch."""
    path = path or index_path()
    cfg, lay = config(), config()["layout"]
    decision = router.route("embed", {"purpose": "reference library build"})
    if not decision.chosen:
        raise RuntimeError(f"no embedding model for the library: {decision.reason}")
    srcs, missing = sources()
    read = [(s, open_document(s["file"], ROOT / cfg["work_dir"] / s["doc_id"])) for s in srcs]
    all_lines = {s["doc_id"]: [page_lines(p) for p in pages] for s, pages in read}
    library_shapes = Counter(sh for doc, pl in all_lines.items()
                             for sh in {_shape(l.text, doc) for lines in pl for l in lines})

    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    rows, embed_texts = [], []
    for s, pages in read:
        doc = s["doc_id"]
        pages_lines = all_lines[doc]
        body_h = body_height(pages_lines)
        mark_bold(s["file"], pages, pages_lines)
        text_lines, notes = [], []
        for page in strip_furniture(pages_lines, doc, library_shapes, len(srcs)):
            body, foot = split_footnotes(page, body_h)
            text_lines += body
            notes.append(foot)
        lines = [l for l in text_lines if _shape(l.text)]
        title = next((l.text for l in lines[:lay["title_lines"]]
                      if _shape(l.text, doc) not in ("", "\0") and len(l.text) >= lay["title_min_chars"]), doc)
        con.execute("insert into documents values (?,?,?,?,?,?)",
                    (doc, title, s["origin"], Path(s["file"]).resolve().relative_to(ROOT).as_posix(),
                     sha256_file(Path(s["file"])), len(pages)))
        for sec in sections(text_lines, body_h) + footnote_sections(notes):
            for part, piece in enumerate(chunks_of(sec)):
                if not piece:
                    continue
                text = "\n".join(l.text for l in piece)
                bbox = [min(l.bbox[0] for l in piece), min(l.bbox[1] for l in piece),
                        max(l.bbox[2] for l in piece), max(l.bbox[3] for l in piece)]
                rows.append((doc, sec["section"], sec["heading"], part, piece[0].page, piece[-1].page,
                             json.dumps([round(v, 1) for v in bbox]), text))
                embed_texts.append(f"{doc} {title}. {sec['heading']}\n{text}")
    con.executemany("insert into chunks (doc_id, section, heading, part, page_first, page_last, bbox, text) "
                    "values (?,?,?,?,?,?,?,?)", rows)
    con.execute("insert into chunks_fts(chunks_fts) values ('rebuild')")
    vectors = embed(embed_texts, decision.chosen, "document")
    ids = [r[0] for r in con.execute("select id from chunks order by id")]
    con.executemany("insert into vectors values (?, ?)", [(i, v.tobytes()) for i, v in zip(ids, vectors)])
    con.executemany("insert into meta values (?, ?)",
                    [("embed_model", decision.chosen), ("config_sha256", sha256_file(CONFIG))])
    con.commit()
    counts = dict(con.execute("select doc_id, count(*) from chunks group by doc_id").fetchall())
    con.close()
    return {"documents": len(srcs), "missing_sources": missing, "embed_model": decision.chosen,
            "chunks": len(rows), "per_document": counts}


# --- searching -------------------------------------------------------------------------

def _ident(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass
class Hit:
    chunk_id: int
    doc_id: str
    title: str
    origin: str
    section: str
    heading: str
    pages: tuple[int, int]
    text: str
    score: float
    why: dict = field(default_factory=dict)

    def citation(self) -> str:
        where = {"0": "document header", "footnotes": "footnotes"}.get(self.section, f"section {self.section}")
        pages = f"p. {self.pages[0]}" if self.pages[0] == self.pages[1] else f"pp. {self.pages[0]}-{self.pages[1]}"
        return f"{self.doc_id}, {where}, {pages}"


def _hit(c: sqlite3.Row, score: float, why: dict) -> Hit:
    return Hit(c["id"], c["doc_id"], c["title"], c["origin"], c["section"], c["heading"],
               (c["page_first"], c["page_last"]), c["text"], score, why)


def references(text: str, doc_ids: list[str]) -> list[tuple[str, str]]:
    """(document, section) pairs a passage points at, by library.yaml's patterns,
    for the documents actually in the index."""
    by_lower = {d.lower(): d for d in doc_ids}
    alt = "|".join(re.escape(d) for d in sorted(doc_ids, key=len, reverse=True))
    out = []
    for pattern in config()["search"]["references"]["patterns"]:
        for m in re.finditer(pattern.replace("{doc}", f"(?P<doc>{alt})"), text, re.I):
            doc = by_lower[m.group("doc").lower()]
            out += [(doc, s) for s in re.findall(r"\d+(?:\.\d+)*", m.group("sections"))]
    return out


@dataclass(frozen=True)
class _Loaded:
    chunks: dict            # chunk id -> row (text, document, section, pages, title, origin)
    doc_ids: list[str]
    embed_model: str
    ids: list[int]
    position: dict          # chunk id -> row of the vector matrix
    matrix: np.ndarray
    vocabulary: frozenset


@lru_cache(maxsize=4)
def _load(path: str, modified: float) -> _Loaded:
    """Everything search needs from the index, read once and kept until the file changes.

    Reading the vectors on every question would cost ~500 ms at 100,000 chunks,
    against ~6 ms for the search itself (measured 2026-09-13).
    """
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    chunks = {r["id"]: r for r in con.execute(
        "select c.*, d.title, d.origin from chunks c join documents d using (doc_id)")}
    doc_ids = [r["doc_id"] for r in con.execute("select doc_id from documents")]
    model = con.execute("select value from meta where key = 'embed_model'").fetchone()["value"]
    ids, blobs = zip(*con.execute("select chunk_id, vector from vectors order by chunk_id").fetchall())
    con.close()
    matrix = np.frombuffer(b"".join(blobs), dtype=np.float32).reshape(len(ids), -1)
    words = frozenset(w for r in chunks.values() for w in re.findall(r"\b[a-z]+\b", r["text"]))
    return _Loaded(chunks, doc_ids, model, list(ids), {cid: i for i, cid in enumerate(ids)}, matrix, words)


def loaded(path: Path | None = None) -> _Loaded:
    path = path or index_path()
    return _load(str(path), path.stat().st_mtime)


def vocabulary(path: Path | None = None) -> frozenset[str]:
    """Every word that appears in lower case somewhere in the library -- ordinary
    words, as opposed to names. A capitalised word that only starts a sentence
    ("Nothing says ...") is checked against this; a name never appears in lower case."""
    return loaded(path).vocabulary


def search(query: str, k: int | None = None, path: Path | None = None,
           follow_references: bool = True) -> list[Hit]:
    """The k best chunks for a question, then the sections those chunks refer to.

    A memo that says "a written delegation under SOP-INSP-001 section 2" cannot
    be read correctly without that section, though the question may share no
    words with it. Referenced sections come after the ranked hits, one hop only,
    with score 0 and why={"referenced_by": ...}, so a scorer can tell them apart.
    """
    cfg = config()["search"]
    k, path = k or cfg["k"], path or index_path()
    index = loaded(path)
    chunks, doc_ids, ids, position = index.chunks, index.doc_ids, index.ids, index.position
    ranks: dict[int, dict[str, int]] = {cid: {} for cid in chunks}
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row

    words = [w for w in re.findall(r"[A-Za-z0-9]+", query) if len(w) > 1]
    if words:
        fts = " OR ".join(f'"{w}"' for w in words)
        for rank, row in enumerate(con.execute(
                "select rowid from chunks_fts where chunks_fts match ? order by bm25(chunks_fts) limit ?",
                (fts, cfg["candidates"]))):
            ranks[row["rowid"]]["keyword"] = rank

    con.close()
    sims = index.matrix @ embed([query], index.embed_model, "query")[0]
    for rank, idx in enumerate(np.argsort(-sims)[:cfg["candidates"]]):
        ranks[ids[idx]]["vector"] = rank

    wanted = {_ident(m.group(0)) for p in cfg["identifier_patterns"] for m in re.finditer(p, query)}
    scored = []
    for cid, r in ranks.items():
        text = chunks[cid]["text"]
        score = sum(1.0 / (cfg["rrf_k"] + rank) for rank in r.values())
        exact = [w for w in wanted if w and (w in _ident(text) or w == _ident(chunks[cid]["doc_id"]))]
        if exact:
            score += cfg["identifier_bonus"] / cfg["rrf_k"] * len(exact)
            r = {**r, "identifier": exact}
        if score > 0:
            scored.append((score, cid, {**r, "cosine": round(float(sims[position[cid]]), 3)}))
    scored.sort(reverse=True)
    hits = [_hit(chunks[cid], round(score, 5), why) for score, cid, why in scored[:k]]
    if follow_references:
        seen, followed = {(h.doc_id, h.section) for h in hits}, 0
        for h in list(hits):
            for key in references(h.text, doc_ids):
                if key in seen or followed >= cfg["references"]["max_sections"]:
                    continue
                seen.add(key)
                found = [c for c in chunks.values() if (c["doc_id"], c["section"]) == key]
                followed += bool(found)
                hits += [_hit(c, 0.0, {"referenced_by": h.citation()}) for c in found]
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=None, help="default: search.k in library.yaml")
    args = ap.parse_args()
    if args.cmd == "build":
        print(json.dumps(build(), indent=2))
        return 0
    for h in search(args.query, args.k):
        print(f"{h.score:.4f}  {h.citation()}  [{h.heading[:50]}]  {h.why}")
        print("        " + h.text[:220].replace("\n", " "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
