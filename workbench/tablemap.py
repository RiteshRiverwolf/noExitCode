"""Placing text into table cells by position -- code only, no model.

PP-StructureV3 reads the *text* of a scan very well and its own *table
structure* badly: on a clean scan it merged the header row with CML-01's row
and shifted that row's values into the next one (results/stage1/NOTES.md
section 3). So the structure is rebuilt here, from geometry:

    tilt    the slope of the header words -- a scan is never quite straight
            (the heavy profile is rotated about 1.5 degrees). Every box is
            straightened by it before rows are assigned; without this, four
            heavy-scan values landed in the wrong row.
    columns where the header words start. A value belongs to the last column
            beginning at or before its left edge.
    rows    bands between the row ids (CML-01, F-02 ...). A band runs from its
            own id down to the next id, so a row whose cells wrap over several
            lines stays one row.

Nothing here knows what an inspection report is; it is given a TableSpec.
What the tables of *our* report look like lives in workbench/scan_reader.py.

The checks are the point. A cell that is not exactly one clean value is not
repaired and not guessed -- it is returned with its problems, and the reader
turns that into NEEDS REVIEW with the crop attached.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from workbench.pagesource import Page, TextItem

EXACT_NUMBER = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*$")
MIN_SCORE = 0.90           # OCR confidence below this: the value goes to review
DARK = 140                 # grey level below which a pixel counts as ink
INK_FLOOR = 15             # never flag fewer dark pixels than this as leftover ink
INK_FACTOR = 4             # ... nor fewer than this many times the page's typical cell


def norm(text: str) -> str:
    """Template words compared bare: 'Min. Req.' and 'Min Req' both -> 'minreq'.

    OCR drops the space in '2. INSPECTION FINDINGS' and turns '.' into ',', so
    punctuation and spacing carry no meaning here.
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


def best_match(key: str, choices: dict[str, str], notes: list[str] | None = None,
               what: str = "", threshold: float = 0.88, margin: float = 0.04) -> str | None:
    """Match one printed word against the template's known words, allowing for OCR.

    This tolerance is for the *template* only -- the headings, column headers
    and labels, which are a small closed set fixed by the form. A value is
    never matched this way: 'l2.32' stays unreadable and goes to review.
    OCR read 'Observation' as 'Obseryation' and 'Equipment Tag' as 'Eguipment
    Tag' on a clean scan; refusing those would lose the whole findings table,
    while accepting them cannot change a number.

    A near match is only taken when it is clearly ahead of the next candidate,
    and every one is written down (notes), so a person can see what was read as
    what.
    """
    if key in choices:
        return choices[key]
    scored = sorted(((SequenceMatcher(None, key, k).ratio(), k) for k in choices), reverse=True)
    if not scored:
        return None
    ratio, matched = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if ratio < threshold or ratio - runner_up < margin:
        return None
    if notes is not None:
        notes.append(f"{what}read {key!r} as {matched!r} ({ratio:.2f} alike)")
    return choices[matched]


@dataclass
class TableSpec:
    """What a table looks like, independent of any one document."""
    name: str
    headers: dict[str, str]              # normalised header word -> field name
    row_id: re.Pattern                   # text of the cell that starts a row
    numeric: tuple[str, ...] = ()        # fields that must be a number exactly as printed
    single_item: tuple[str, ...] = ()    # fields that must hold exactly one piece of text


@dataclass
class Cell:
    field: str
    row: str
    page: int
    items: list[TextItem] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """The cell's text in reading order; several lines join with a space."""
        ordered = sorted(self.items, key=lambda i: (round(i.bbox[1] / 8), i.bbox[0]))
        return " ".join(i.text for i in ordered).strip()

    @property
    def score(self) -> float:
        return min((i.score for i in self.items), default=0.0)

    @property
    def bbox(self) -> tuple[float, float, float, float] | None:
        if not self.items:
            return None
        return (min(i.bbox[0] for i in self.items), min(i.bbox[1] for i in self.items),
                max(i.bbox[2] for i in self.items), max(i.bbox[3] for i in self.items))

    @property
    def ok(self) -> bool:
        return not self.problems and bool(self.items)


@dataclass
class TableRead:
    spec: TableSpec
    page: int
    rows: dict[str, dict[str, Cell]]
    geometry: dict
    problems: list[str] = field(default_factory=list)


def _straightener(anchors: list[TextItem]):
    """A function that removes the page's tilt from a box's centre y.

    The slope is the least-squares fit through the header words, which are
    printed on one line: on a straight page it is ~0 and changes nothing.
    """
    pts = [a.center for a in anchors]
    mx = statistics.mean(p[0] for p in pts)
    my = statistics.mean(p[1] for p in pts)
    denom = sum((x - mx) ** 2 for x, _ in pts)
    slope = sum((x - mx) * (y - my) for x, y in pts) / denom if denom else 0.0

    def straight(item_or_box) -> float:
        b = item_or_box.bbox if isinstance(item_or_box, TextItem) else item_or_box
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        return cy - slope * (cx - mx)

    def straight_top(item: TextItem) -> float:
        cx = (item.bbox[0] + item.bbox[2]) / 2
        return item.bbox[1] - slope * (cx - mx)

    return straight, straight_top, slope, mx


def _header_row(items: list[TextItem], spec: TableSpec,
                notes: list[str] | None) -> dict[str, TextItem] | None:
    """The table's header, as one printed line.

    A column header must not be looked for word by word anywhere on the page:
    in this report 'Observation' is both the heading of the findings column and
    one of the four severity grades. On a clean scan where OCR wrote the real
    heading as 'Obseryation', matching by word alone picked the *severity cell
    two rows down* as the column header and lost the first two findings with it.

    So candidates are grouped into printed lines, and the line that carries the
    most of the table's columns wins -- the header of a table is on one line,
    and a stray word in a data cell is not.
    """
    SPREAD = 15.0            # how far off its own line a header word may sit, in pixels
    MAX_TILT = 0.10          # no page is more crooked than this (heavy scans reach ~0.026)
    candidates: list[tuple[TextItem, str, bool]] = []
    for item in items:
        key = norm(item.text)
        if key in spec.headers:
            candidates.append((item, spec.headers[key], True))
        else:
            near = best_match(key, spec.headers)
            if near:
                candidates.append((item, near, False))
    if not candidates:
        return None

    # The header is a straight line through the candidates, not a horizontal
    # band: a scan is tilted, and over the width of the page the heavy profile's
    # 1.5 degrees lifts one end of the header row by about 30 px -- more than the
    # gap between two table rows. So every pair of candidates proposes a line and
    # the line carrying the most columns wins.
    def line_through(a: TextItem, b: TextItem):
        (ax, ay), (bx, by) = a.center, b.center
        if abs(bx - ax) < 100:
            return None
        slope = (by - ay) / (bx - ax)
        if abs(slope) > MAX_TILT:
            return None
        return [c for c in candidates
                if abs(c[0].center[1] - (ay + slope * (c[0].center[0] - ax))) <= SPREAD]

    def rank(line):                        # most columns covered; exact words preferred
        fields = {f for _, f, _ in line}
        return (len(fields), sum(1 for _, _, exact in line if exact), -line[0][0].center[1])

    lines = [g for a, _, _ in candidates for b, _, _ in candidates
             if (g := line_through(a, b))]
    lines.append(candidates[:1])            # a one-column table still has a header
    best = max(lines, key=rank)
    heads: dict[str, TextItem] = {}
    for item, fieldname, exact in sorted(best, key=lambda c: not c[2]):   # exact ones first
        if fieldname not in heads:
            heads[fieldname] = item
            if not exact and notes is not None:
                best_match(norm(item.text), spec.headers, notes, f"{spec.name} column: ")
    return heads if not set(spec.headers.values()) - set(heads) else None


def find_table(page: Page, spec: TableSpec, top: float = 0.0, bottom: float | None = None,
               notes: list[str] | None = None) -> TableRead | None:
    """Locate and read one table on one page, between two heights of the page.

    Returns None when the header words are not all there -- on a continuation
    page with no repeated header, or simply no such table. The caller decides
    what that means; nothing is invented here.
    """
    bottom = page.height if bottom is None else bottom
    in_region = [i for i in page.items if top <= (i.bbox[1] + i.bbox[3]) / 2 <= bottom]

    heads = _header_row(in_region, spec, notes)
    if heads is None:
        return None

    straight, straight_top, slope, mx = _straightener(list(heads.values()))
    header_bottom = max(straight(h) for h in heads.values()) + 12
    columns = sorted((h.bbox[0], name) for name, h in heads.items())

    anchors = sorted((straight_top(i), i.text.strip(), i) for i in in_region
                     if spec.row_id.fullmatch(i.text.strip()) and straight(i) > header_bottom)
    if not anchors:
        return None

    # A row band runs from its own id to the next one; the last reaches the end
    # of the region, so a wrapped final cell is not cut off.
    bands = []
    for n, (y_top, row_id, item) in enumerate(anchors):
        y_end = anchors[n + 1][0] - 2 if n + 1 < len(anchors) else bottom
        bands.append((row_id, y_top - 6, y_end))

    rows = {row_id: {f: Cell(field=f, row=row_id, page=page.number)
                     for f in spec.headers.values()} for row_id, _, _ in bands}
    problems: list[str] = []
    seen = set()
    for row_id, _, _ in bands:
        if row_id in seen:
            problems.append(f"{spec.name}: row id {row_id} appears twice on page {page.number}")
        seen.add(row_id)

    placed: list[tuple[str, TextItem, float]] = []
    for item in in_region:
        cy = straight(item)
        if cy <= header_bottom:
            continue
        band = next(((rid) for rid, y0, y1 in bands if y0 <= cy < y1), None)
        if band is None:
            continue                       # outside the table altogether
        left = item.bbox[0]
        col = [name for x0, name in columns if x0 <= left + 12]
        if not col:
            continue
        placed.append((band, item, cy))

    # Where does the table end? The last row's band has no next row to stop it,
    # so it would swallow whatever is printed underneath -- the corrosion-rate
    # block, a footer. The rows of a table are printed at a steady line pitch,
    # and what follows the table is set off by white space, so the last band is
    # cut at the first vertical gap clearly wider than that pitch.
    last_row = bands[-1][0]
    cut = _end_of_table([(item, cy) for rid, item, cy in placed if rid != last_row],
                        [(item, cy) for rid, item, cy in placed if rid == last_row], columns)
    if cut is not None:
        placed = [(rid, item, cy) for rid, item, cy in placed if rid != last_row or cy < cut]
        bands[-1] = (last_row, bands[-1][1], cut)

    for band, item, _ in placed:
        left = item.bbox[0]
        col = [name for x0, name in columns if x0 <= left + 12]
        rows[band][col[-1]].items.append(item)

    geometry = {"slope": slope, "mx": mx, "header_bottom": header_bottom,
                "columns": [(round(x), n) for x, n in columns],
                "bands": [(r, round(y0), round(y1)) for r, y0, y1 in bands]}
    return TableRead(spec=spec, page=page.number, rows=rows, geometry=geometry, problems=problems)


# --- checks ------------------------------------------------------------------

def _end_of_table(body: list[tuple[TextItem, float]], last: list[tuple[TextItem, float]],
                  columns: list[tuple[float, str]]) -> float | None:
    """The height at which the final row stops, or None to leave it open.

    The last row has no next row to stop it, so it would otherwise swallow
    whatever is printed below the table. What separates the two is alignment,
    not white space: every line of a table sits on its columns' edges, while
    the block underneath is set to its own grid. On insp_1002 all four values
    of each thickness row start within 1 px of their column, and the corrosion
    -rate line below misses by 8, 131, 19 and 131 px. (White space alone does
    not separate them: the gap there is 1.4 row pitches, well inside what a
    wrapped cell can leave.)

    A line of the last band is part of the table when most of its pieces sit on
    a column edge. The first line always does -- it holds the row's own id.
    """
    if not last:
        return None
    edges: list[float] = []
    for x0, name in columns:
        lefts = [i.bbox[0] for i, _ in body
                 if [n for cx, n in columns if cx <= i.bbox[0] + 12][-1:] == [name]]
        edges.append(statistics.median(lefts) if lefts else x0)
    ys = sorted(y for _, y in body)
    pitches = [b - a for a, b in zip(ys, ys[1:]) if 3 < b - a < 80]
    tol = max(6.0, 0.2 * statistics.median(pitches)) if pitches else 8.0

    lines: list[list[tuple[TextItem, float]]] = []
    for item, y in sorted(last, key=lambda p: p[1]):
        if lines and y - lines[-1][0][1] <= 6:
            lines[-1].append((item, y))
        else:
            lines.append([(item, y)])
    for n, line in enumerate(lines):
        aligned = sum(1 for item, _ in line
                      if min(abs(item.bbox[0] - e) for e in edges) <= tol)
        if aligned < 0.6 * len(line) and n > 0:
            return (lines[n - 1][0][1] + line[0][1]) / 2
    return None


def check_cells(table: TableRead, page: Page) -> None:
    """Fill in each cell's problems. Code never repairs a value; it reports it.

    The leftover-ink check only applies to a page read by OCR: on a text-layer
    page the characters are the document's own, so there is no smudge to miss.
    """
    from workbench.pagesource import OCR_READER

    inks: dict[tuple[str, str], int] = {}
    if page.read_by == OCR_READER and table.spec.numeric:
        inks = _cell_ink(table, page)

    for row_id, cells in table.rows.items():
        for name, cell in cells.items():
            numeric = name in table.spec.numeric
            single = numeric or name in table.spec.single_item
            if not cell.items:
                cell.problems.append("empty")
                continue
            if single and len(cell.items) != 1:
                cell.problems.append(f"{len(cell.items)} pieces of text in one cell "
                                     f"({' | '.join(i.text for i in cell.items)})")
            if numeric and not EXACT_NUMBER.match(cell.text):
                cell.problems.append(f"not a number as printed ({cell.text!r})")
            if cell.score < MIN_SCORE:
                cell.problems.append(f"low confidence {cell.score:.3f}")

    _check_decimals(table)

    if inks:
        limit = max(INK_FLOOR, INK_FACTOR * statistics.median(sorted(inks.values())))
        for (row_id, name), ink in inks.items():
            if ink > limit:
                table.rows[row_id][name].problems.append(
                    f"leftover ink in the cell: {ink} px (limit {limit:.0f})")
        table.geometry["ink_limit"] = round(limit)
        table.geometry["ink"] = {f"{r}.{c}": v for (r, c), v in inks.items()}


def _check_decimals(table: TableRead) -> None:
    """A column of a survey is printed to a fixed number of decimals.

    This is what catches the damage that everything else misses. The breached
    reading 12.32 with its last digit smudged is read as a clean '12.3' -- by
    PP-StructureV3 at confidence 1.000, and by qwen in 13 of 18 attempts. It
    stays below the minimum, so the verdict does not change and nothing looks
    wrong; but the same failure on a different cell turns ESCALATE into NO
    TRIGGER. Confidence does not see it. Leftover ink does not see the erased
    version of it at all -- a white gap leaves no pixels to count.

    A missing digit does change one thing: the value no longer matches the
    precision of its own column (12.3 among 19.67, 18.75, 18.47). That is a
    property of the printed form, so code can check it with no model and no
    threshold to tune.

    Deliberately conservative: it needs at least MIN_PEERS other values that
    agree with each other, and it raises the cell for review -- it never edits
    the number or decides that the reading is wrong.
    """
    MIN_PEERS = 3
    for name in table.spec.numeric:
        places: dict[str, int] = {}
        for row_id, cells in table.rows.items():
            m = EXACT_NUMBER.match(cells[name].text)
            if m:
                value = m.group(1)
                places[row_id] = len(value.split(".")[1]) if "." in value else 0
        if len(places) <= MIN_PEERS:
            continue
        counts = statistics.Counter(places.values()) if hasattr(statistics, "Counter") else None
        if counts is None:
            from collections import Counter
            counts = Counter(places.values())
        usual, n_usual = counts.most_common(1)[0]
        if n_usual < MIN_PEERS:
            continue
        for row_id, dp in places.items():
            if dp != usual:
                table.rows[row_id][name].problems.append(
                    f"written to {dp} decimal place(s) where the rest of the column uses "
                    f"{usual} -- a digit may be missing")


def _cell_ink(table: TableRead, page: Page) -> dict[tuple[str, str], int]:
    """Dark pixels inside a numeric cell that no recognised text box covers.

    PP-StructureV3 read the blurred '12.32' as '12.3' at confidence 1.000, and
    qwen read it the same way -- two readers agreeing on a wrong value. The ink
    left by the digit they both dropped is the only trace in the page itself.
    NOT yet trustworthy on its own: an undamaged cell on a heavy scan reached
    46 px of speckle against the smudge's 76. It sends a cell to a person; it
    never decides anything.
    """
    from PIL import Image

    columns = table.geometry["columns"]
    names = [n for _, n in columns]
    slope, mx = table.geometry["slope"], table.geometry["mx"]
    with Image.open(page.image_path) as im:
        grey = im.convert("L")
        pixels = grey.load()
        w, h = grey.size
        out: dict[tuple[str, str], int] = {}
        for row_id, y0, y1 in table.geometry["bands"]:
            for name in table.spec.numeric:
                i = names.index(name)
                x_start = columns[i][0] - 4
                x_end = columns[i + 1][0] - 10 if i + 1 < len(columns) else x_start + 140
                boxes = [it.bbox for it in table.rows[row_id][name].items]
                count = 0
                for x in range(max(0, int(x_start)), min(w, int(x_end))):
                    shift = slope * (x - mx)
                    for y in range(max(0, int(y0 + shift)), min(h, int(y1 + shift))):
                        if any(b[0] - 3 <= x <= b[2] + 3 and b[1] - 3 <= y <= b[3] + 3 for b in boxes):
                            continue
                        if pixels[x, y] < DARK:
                            count += 1
                out[(row_id, name)] = count
    return out


# --- key-value blocks --------------------------------------------------------

def read_pairs(page: Page, labels: dict[str, str], top: float = 0.0,
               bottom: float | None = None, notes: list[str] | None = None) -> dict[str, Cell]:
    """'Report No.  MRPL/INSP/2026/8013' -- the value is the text to the right.

    No column geometry: the label is found by its own words and the value is
    the nearest text on the same line to its right. Two label/value pairs per
    printed row, which is why 'the same line' is decided by vertical overlap
    and not by a row band.
    """
    bottom = page.height if bottom is None else bottom
    region = [i for i in page.items if top <= (i.bbox[1] + i.bbox[3]) / 2 <= bottom]
    out: dict[str, Cell] = {}
    for exact_only in (True, False):       # every clean label claimed before any near one
        for item in region:
            key = norm(item.text)
            if exact_only:
                name = labels.get(key)
            else:
                left = {k: v for k, v in labels.items() if v not in out}
                name = None if key in labels else best_match(key, left, notes, "label: ")
            if not name or name in out:
                continue
            ly0, ly1 = item.bbox[1], item.bbox[3]
            same_line = [o for o in region
                         if o is not item and o.bbox[0] >= item.bbox[2]
                         and min(ly1, o.bbox[3]) - max(ly0, o.bbox[1]) > (ly1 - ly0) * 0.4]
            cell = Cell(field=name, row=item.text.strip(), page=page.number)
            if same_line:
                nearest = min(same_line, key=lambda o: o.bbox[0])
                cell.items = [o for o in same_line if o.bbox[0] < nearest.bbox[2] + 6]
            else:
                cell.problems.append("no value printed next to this label")
            out[name] = cell
    return out


def read_paragraph(page: Page, top: float, bottom: float) -> Cell:
    """Free text between two heights, in reading order (the inspector's summary)."""
    items = [i for i in page.items if top <= (i.bbox[1] + i.bbox[3]) / 2 <= bottom]
    cell = Cell(field="paragraph", row="", page=page.number, items=items)
    if not items:
        cell.problems.append("no text found")
    return cell


def crop(page: Page, bbox: tuple[float, float, float, float], out_path: Path,
         pad: int = 10) -> Path:
    """The picture of one value, for the engineer who has to sign the note.

    A digit that was physically lost from the page leaves nothing for any
    reader to find, so the last check is always a person looking at this.
    """
    from PIL import Image

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(page.image_path) as im:
        box = (max(0, int(bbox[0]) - pad), max(0, int(bbox[1]) - pad),
               min(im.width, int(bbox[2]) + pad), min(im.height, int(bbox[3]) + pad))
        im.crop(box).save(out_path)
    return out_path
