"""The one part a model writes: the summary paragraph, checked before use.

The model gets the evidence and the rules' decision, plus the guidance and
pitfalls from the procedural graph's edges, and writes 3-5 sentences. Code
then checks it:
  - every number must appear in the evidence or the rules' results;
  - no approval language ("approved", "fit for service", "safe to operate");
  - an escalation must name every CML that breached;
  - a "no trigger" result must not claim a breach.
If a check fails the model gets one repair attempt, told exactly what was
wrong. After that a plain summary written by code is used, and the note says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx

from workbench.evidence import EvidenceSet
from workbench.rules import Decision, allowed_numbers

OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "granite4.1:8b"
HYPHENS = re.compile("[‐‑‒–—―−]")
# A sentence claims a thickness breach when shortfall wording sits close to a
# minimum or required value. On 2026-09-11 granite used "below the minimum",
# "falling short of the required" and "undershot minimums" -- the last two
# inventing breaches that the rules had not found.
BREACH_CLAIM = re.compile(
    r"\b(below|undershot|under-?thickness|short of|falls? short|falling short|less than|fails? to meet"
    r"|insufficient|deficien\w*|violat\w*|breach\w*)\b[^.]{0,40}?\b(min\w*|required|allowable)\b",
    re.IGNORECASE)
# Verdicts only people give. "Approved WPS" quoted from a report is not one.
VERDICT = re.compile(
    r"\b(?:is|are|be|been|was|were|hereby)\s+(?:approved|cleared)\b|\bapproved for\b|\bI approve\b"
    r"|\bfit for (?:service|purpose)\b|\bsafe to (?:operate|continue)\b|\bsigned[- ]off\b",
    re.IGNORECASE)

SYSTEM = (
    "You write the summary paragraph of a DRAFT inspection approval note that engineers will "
    "review. Use only the facts given. Do not invent numbers, names or dates, and do not round "
    "numbers. Never say the equipment is approved, safe or fit for service: people decide that. "
    "Say what the rules engine concluded and why, mention the key findings, and say what needs "
    "engineering attention. Use the words Critical, Major, Minor and Observation only as the "
    "report's grades. Write 3 to 5 plain sentences, under 110 words: no headings, no lists, no sign-off."
)
MAX_WORDS = 120
STYLE_ONLY = ("longer than",)  # style problems: repaired if possible, never a reason to discard


@dataclass
class Summary:
    text: str
    written_by: str
    attempts: list[dict] = field(default_factory=list)


def facts_for_model(ev: EvidenceSet, decision: Decision, guidance: str = "") -> str:
    h = ev.header
    lines = [
        f"Equipment: {field(h, 'equipment_tag')} ({field(h, 'equipment_name')}), {field(h, 'unit')}.",
        f"Inspection: {field(h, 'inspection_type')} on {field(h, 'inspection_date')}; "
        f"report {field(h, 'report_no')}.",
        f"Rules engine outcome: {decision.outcome}.",
    ]
    for t in decision.triggers:
        lines.append(f"Rule {t.rule_id} ({t.title}) triggered: {t.detail}.")
    for t in decision.review_items:
        lines.append(f"Needs review ({t.rule_id}): {t.detail}.")
    if decision.outcome == "NO TRIGGER":
        lines.append("No evaluated rule triggered. This is not a statement of fitness for service.")
    counts = severity_counts(ev)
    lines.append("Findings by severity (counted by code): "
                 + ", ".join(f"{n} {sev}" for sev, n in counts.items()) + ".")
    lines.append("Findings:")
    for f in ev.findings:
        lines.append(f"- {f.finding_id} [{f.severity}] {f.description} Recommendation: {f.recommendation}")
    # The rules engine has already compared every reading with its minimum; give
    # the model the result, so it describes the decision instead of redoing it.
    # (granite invented breaches for insp_1006 and insp_1008 when left to compare.)
    breached = {t.subject for t in decision.triggers if t.rule_id == "THK-01"}
    lines.append("Thickness readings (current / minimum required, mm) -- status decided by the rules engine:")
    for r in ev.readings:
        status = "BELOW MINIMUM (rule THK-01)" if r.cml_id in breached else "above minimum, no action from rules"
        lines.append(f"- {r.cml_id} {r.location}: {r.current_mm} / {r.min_required_mm} -> {status}")
    if not breached:
        lines.append("No thickness reading is below its minimum.")
    if guidance:
        lines += ["", "Guidance for this step:", guidance]
    return "\n".join(lines)


# Guideline from the team review (11 Sep): "A report can contain the correct
# numbers but swap their meanings." A number next to "minimum/required" must be
# a minimum from the report; a number next to "current/measured" must be a
# measured value. lfm2.5 wrote "Minimum required 12.32 mm" (a measured value).
# "minimum measured/recorded thickness" means the lowest reading, not the
# required value, so it is not a minimum cue. "thickness of" is not a
# measured-value cue: "the minimum required thickness of 12.7 mm" is correct.
MIN_CONTEXT = re.compile(
    r"\b(?:min(?:imum|\.)?(?!\s+(?:\w+\s+)?(?:measured|recorded|observed|reading))|required|allowable)\b"
    r"[^.\d]{0,25}?(\d+\.\d+)", re.IGNORECASE)
CURRENT_CONTEXT = re.compile(
    r"\b(?:current\w*|measured|measuring|measures|reading of)\b[^.\d]{0,25}?(\d+\.\d+)", re.IGNORECASE)
WRONG_UNIT = re.compile(r"\d+(?:\.\d+)?\s*(?:inch(?:es)?|in\.|cm|\")", re.IGNORECASE)
NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}
SEVERITY_COUNT = re.compile(r"\b(\d+)\s+(critical|major|minor|observation)s?\b", re.IGNORECASE)


def severity_counts(ev: EvidenceSet) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in ev.findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts


def _forms(values) -> set[str]:
    return {form for v in values if v is not None for form in (str(v), f"{v:.2f}", str(v.normalize()))}


def check(text: str, ev: EvidenceSet, decision: Decision) -> list[str]:
    problems = []
    plain = HYPHENS.sub("-", text)
    allowed = allowed_numbers(ev, decision)
    bad = sorted({n for n in re.findall(r"\d+(?:\.\d+)?", plain) if n not in allowed})
    if bad:
        problems.append(f"numbers that are not in the evidence: {', '.join(bad)}")

    minimums = _forms(r.min_required_mm for r in ev.readings)
    measured = _forms(v for r in ev.readings for v in (r.current_mm, r.previous_mm, r.nominal_mm))
    for m in MIN_CONTEXT.finditer(plain):
        if m.group(1) in measured and m.group(1) not in minimums:
            problems.append(f"gives {m.group(1)} mm as a minimum, but it is a measured value")
    for m in CURRENT_CONTEXT.finditer(plain):
        if m.group(1) in minimums and m.group(1) not in measured:
            problems.append(f"gives {m.group(1)} mm as a measured value, but it is a minimum")
    if WRONG_UNIT.search(plain):
        problems.append(f"uses a unit the report does not ('{WRONG_UNIT.search(plain).group(0)}'); readings are in mm")

    worded = re.sub(r"\b(" + "|".join(NUMBER_WORDS) + r")\b",
                    lambda m: NUMBER_WORDS[m.group(1).lower()], plain, flags=re.IGNORECASE)
    counts = {k.lower(): v for k, v in severity_counts(ev).items()}
    for m in SEVERITY_COUNT.finditer(worded):
        said, sev = int(m.group(1)), m.group(2).lower()
        if said != counts.get(sev, 0):
            problems.append(f"says {said} {sev} finding(s); the report has {counts.get(sev, 0)}")
    m = VERDICT.search(plain)
    if m:
        problems.append(f"gives a verdict ('{m.group(0)}'): only people approve")

    breached = {t.subject for t in decision.triggers if t.rule_id == "THK-01"}
    for t in breached:
        if t not in plain:
            problems.append(f"does not mention {t}, which is below its minimum")
    # Any claim that a reading is below its minimum must be about a CML the rules
    # flagged. On 2026-09-11 granite wrote "Nozzle N-3 neck thickness is below the
    # minimum required at 12.11 mm (minimum 7.8 mm)" for insp_1006 -- invented.
    locations = {r.cml_id: r.location for r in ev.readings}
    for sentence in re.split(r"(?<=[.!?])\s+", plain):
        if not BREACH_CLAIM.search(sentence):
            continue
        named = {c for c, loc in locations.items() if c in sentence or loc.lower() in sentence.lower()}
        wrong = sorted(named - breached)
        if wrong:
            problems.append(f"says {', '.join(wrong)} is below its minimum; the rules found it is not")
        elif not named and not breached:
            problems.append("claims a thickness breach that the rules did not find")
    words = len(plain.split())
    if words > MAX_WORDS + 10:
        problems.append(f"longer than {MAX_WORDS} words ({words}); cut it to under 110")
    if not plain.strip():
        problems.append("empty")
    return problems


NOT_READ = "(not read from the document)"


def field(header: dict, key: str) -> str:
    """A header value for a sentence -- or a plain statement that it was not read.

    OCR can miss a label on a real scan. A missing Inspection Type crashed this
    summary on insp_1005 and insp_1008 ('NoneType' object has no attribute
    'lower'), so the run stopped for a person over a field no decision depends
    on; and the same gap reached the model's instructions as the word "None".
    """
    value = header.get(key)
    return NOT_READ if value in (None, "") else str(value)


def code_summary(ev: EvidenceSet, decision: Decision) -> str:
    h = ev.header
    kind = h.get("inspection_type")
    source = f"{kind.lower()} report" if kind else "inspection report"
    parts = [f"The rules engine returned {decision.outcome} for {field(h, 'equipment_tag')} "
             f"({field(h, 'equipment_name')}), from {source} {field(h, 'report_no')}."]
    for t in decision.triggers:
        parts.append(f"Rule {t.rule_id}: {t.detail.rstrip('.')}.")
    for t in decision.review_items:
        parts.append(f"Needs review: {t.detail.rstrip('.')}.")
    if decision.outcome == "NO TRIGGER":
        parts.append("No evaluated rule triggered; this is not a statement of fitness for service.")
    parts.append(f"The report records {len(ev.findings)} findings and {len(ev.readings)} "
                 "thickness readings, tabulated below. An engineer must review this draft.")
    return " ".join(parts)


def write_summary(ev: EvidenceSet, decision: Decision, model: str | None = DEFAULT_MODEL,
                  guidance: str = "", max_attempts: int = 2) -> Summary:
    if not model:
        return Summary(code_summary(ev, decision), "code (no model requested)")
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": facts_for_model(ev, decision, guidance)}]
    attempts: list[dict] = []
    for i in range(1, max_attempts + 1):
        try:
            r = httpx.post(OLLAMA_CHAT, timeout=300, json={
                "model": model, "messages": messages, "stream": False,
                "options": {"temperature": 0.2, "num_ctx": 4096}})
            r.raise_for_status()
            text = r.json()["message"]["content"].strip()
        except Exception as e:
            attempts.append({"attempt": i, "error": f"{type(e).__name__}: {e}"})
            break
        problems = check(text, ev, decision)
        safety = [p for p in problems if not p.startswith(STYLE_ONLY)]
        attempts.append({"attempt": i, "text": text, "problems": problems})
        if not problems:
            return Summary(text, model, attempts)
        if not safety and i == max_attempts:
            # Accurate but long: keep it, and say so in the record.
            attempts[-1]["accepted_with_style_issue"] = problems
            return Summary(text, model, attempts)
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "Your summary has these problems: "
                      + "; ".join(problems) + ". Rewrite it, fixing them, using only the facts given."}]
    return Summary(code_summary(ev, decision), f"code (fallback after {model} failed the checks)", attempts)
