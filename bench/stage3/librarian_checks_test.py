"""The Librarian's checks, on hand-made replies: what must be caught, and what must pass.

    .venv\\Scripts\\python bench\\stage3\\librarian_checks_test.py

No model and no GPU: each case is a reply a model could give, checked by
workbench.librarian.check against passages written out below. Run it after any
change to the checks or to the librarian's settings in workbench/agents.yaml.
Needs the library index (for its vocabulary): python -m workbench.library build.

Every case here is one that happened, or the trap next to one that happened
(results/stage3/librarian_granite4.1-8b.json). One known gap is recorded as a
case that passes: a refusal's note that STARTS with an invented name. The note
only asserts an absence, and without a dictionary a sentence-starting name and
an ordinary word ("Nothing says ...") cannot be told apart there.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from mcp_servers.audit import AuditLog  # noqa: E402
from workbench import librarian  # noqa: E402
from workbench.library import Hit  # noqa: E402

MEMO = Hit(1, "MEMO-2026-003", "Delegation of signing authority during the 2026 turnaround", "synthetic", "1",
           "Delegation of signing authority", (1, 1),
           "From 15 January 2026 to 28 February 2026, while I am on site with the turnaround team, Senior Inspection "
           "Engineer R. Menon may sign approval notes on my behalf. This is a written delegation under SOP-INSP-001 "
           "section 2. Approval notes for any Critical finding are not covered by this delegation and remain with me.",
           0.03)
ROLES = Hit(2, "SOP-INSP-001", "Roles", "synthetic", "2", "Roles and authority", (1, 1),
            "Only the Head of the Inspection Department may approve continued operation of equipment for which an "
            "escalation trigger has fired. When the Head is absent this authority may be delegated to a Senior "
            "Inspection Engineer, never lower, and only in writing.", 0.0)
CLADDING = Hit(3, "SOP-INSP-004", "External Corrosion, Coatings and Insulation", "synthetic", "5",
               "Damaged insulation cladding", (1, 1),
               "Damaged or displaced insulation cladding with no metal loss is graded Minor. This applies "
               "OISD-STD-118 Cl. 6.2.", 0.02)
VALVES = Hit(4, "SOP-INSP-007", "Pressure Relief Devices", "synthetic", "2", "Test intervals", (1, 1),
             "A pressure safety valve in general hydrocarbon service is bench tested and overhauled at intervals of no "
             "more than 36 months. In fouling or corrosive service the interval is no more than 24 months.", 0.02)
PASSAGES = {"P1": MEMO, "P2": ROLES, "P3": CLADDING, "P4": VALVES}
Q = "Who could sign an approval note for a Major finding on 10 February 2026?"


def s(text: str, *sources: str) -> dict:
    return {"text": text, "sources": list(sources)}


def answered(*sentences: dict) -> dict:
    return {"answerable": True, "missing": "", "sentences": list(sentences)}


def refused(missing: str, *sentences: dict) -> dict:
    return {"answerable": False, "missing": missing, "sentences": list(sentences)}


# (name, reply, question, should the checks find a problem?)
CASES = [
    ("good answer", answered(
        s("Senior Inspection Engineer R. Menon could sign it, under a written delegation from 15 January 2026 "
          "to 28 February 2026.", "P1"),
        s("The procedure allows delegation to a Senior Inspection Engineer, never lower, and only in writing.", "P2")),
     Q, False),
    ("invented number", answered(s("Menon could sign until 31 March 2026.", "P1")), Q, True),
    ("number from the wrong passage", answered(s("Delegation runs from 15 January 2026.", "P2")), Q, True),
    ("cites a passage the search did not return", answered(s("R. Menon could sign.", "P9")), Q, True),
    ("cites nothing", answered(s("R. Menon could sign.")), Q, True),
    ("invented name", answered(s("Senior Inspection Engineer R. Sharma could sign.", "P1")), Q, True),
    ("invented name starting a sentence", answered(s("Sharma could sign approval notes.", "P1")), Q, True),
    ("invented identifier", answered(s("This is a delegation under SOP-INSP-009 section 2.", "P1")), Q, True),
    ("invented quotation", answered(s('The memo says "Menon has full authority".', "P1")), Q, True),
    ("names its own passage's document (granite, Q01)", answered(
        s("OISD-STD-118 Cl. 6.2 is applied in SOP-INSP-004 section 5, damaged insulation cladding.", "P3")),
     "Which procedure applies OISD-STD-118 Cl. 6.2?", False),
    ("restates the question's date as a fact (granite, Q09)",
     answered(s("R. Menon could sign on 10 February 2026.", "P1")), Q, True),
    ("false-premise number taken from the question",
     answered(s("A valve in fouling service is tested every 12 months.", "P4")),
     "Is a pressure safety valve in fouling or corrosive service tested every 12 months?", True),
    ("false-premise name taken from the question", answered(s("R. Sharma holds a written delegation.", "P1")),
     "Does R. Sharma hold a written delegation?", True),
    ("honest refusal", refused("The passages do not give the name of the Head of the Inspection Department."), Q, False),
    ("refusal naming a passage label (granite, U04)",
     refused("Passage P1 mentions an 'approved coating system' but does not name a product."),
     "Which coating product is approved?", False),
    ("refusal starting with an ordinary word", refused("Nothing says who signs on 10 February 2026."), Q, False),
    ("refusal inventing a name after a title", refused("The Head is Dr. Kulkarni, but the passages do not say so."),
     Q, True),
    ("refusal inventing a name after an initial", refused("It was signed by R. Kulkarni instead."), Q, True),
    ("KNOWN GAP: refusal starting with an invented name", refused("Kulkarni is not named anywhere."), Q, False),
    ("refusal that still answers", refused("unclear", s("R. Menon.", "P1")), Q, True),
    ("not the JSON asked for", "R. Menon could sign", Q, True),
]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        librarian._LOG = AuditLog("librarian-test", Path(tmp) / "librarian_test.jsonl")   # the real log stays clean
        failed = 0
        for name, reply, question, expect_problem in CASES:
            problems = librarian.check(reply, PASSAGES, question)
            good = bool(problems) == expect_problem
            failed += not good
            print(f"{'ok  ' if good else 'FAIL'} {name:52} {problems}")
        try:
            librarian.call_tool("run_python", code="print(1)")
            print("FAIL a tool outside the librarian's list was allowed")
            failed += 1
        except librarian.ToolNotAllowed:
            print("ok   a tool outside the librarian's list is refused")
        librarian._LOG = None
    print(f"\n{len(CASES) + 1 - failed}/{len(CASES) + 1} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
