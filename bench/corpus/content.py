"""Realistic content generation for synthetic inspection reports.

Vocabulary, equipment tagging and clause-reference conventions follow Indian
refinery practice (OISD) and API 510/570. Deterministic given a seed, so a
corpus is reproducible and a regression in OCR/extraction can be traced to a
specific document.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from .schema import Finding, InspectionReport, ThicknessReading

# --- Refinery domain vocabulary -------------------------------------------

PLANTS = [
    "Mangalore Refinery — Phase III",
    "Mangalore Refinery — Phase II",
    "Mangalore Refinery — Aromatic Complex",
]

UNITS = [
    ("CDU-I", "Crude Distillation Unit"),
    ("VDU-II", "Vacuum Distillation Unit"),
    ("FCCU", "Fluidised Catalytic Cracking Unit"),
    ("DHDT", "Diesel Hydrotreating Unit"),
    ("SRU-III", "Sulphur Recovery Unit"),
    ("NHT", "Naphtha Hydrotreating Unit"),
    ("CCR", "Continuous Catalytic Reformer"),
    ("HGU", "Hydrogen Generation Unit"),
]

EQUIPMENT = [
    ("V", "Separator Vessel", "vessel"),
    ("V", "Knock-out Drum", "vessel"),
    ("V", "Reflux Accumulator", "vessel"),
    ("C", "Fractionation Column", "column"),
    ("C", "Stripper Column", "column"),
    ("E", "Shell & Tube Heat Exchanger", "exchanger"),
    ("E", "Feed/Effluent Exchanger", "exchanger"),
    ("T", "Storage Tank", "tank"),
    ("R", "Reactor", "reactor"),
]

SERVICE_FLUIDS = [
    "Sour Water", "Crude Oil", "Heavy Vacuum Gas Oil", "Light Naphtha",
    "Hydrogen Rich Gas", "Amine (MDEA) Solution", "Kerosene",
    "Atmospheric Residue", "Sour Gas (H2S bearing)", "Diesel",
]

INSPECTION_TYPES = [
    "External Visual Inspection",
    "Internal Visual Inspection",
    "Ultrasonic Thickness Survey",
    "On-Stream Inspection",
    "Turnaround Inspection",
]

# (description, severity, clause, recommendation)
FINDING_POOL = [
    ("Localised external corrosion observed on shell plate adjacent to support saddle. "
     "Coating breakdown over approximately 0.4 m² with visible rust scaling.",
     "Minor", "OISD-STD-116 Cl. 7.3",
     "Remove loose scale, surface prepare to St-3 and re-apply approved coating system during next available shutdown."),

    ("Corrosion Under Insulation (CUI) detected at insulation termination near nozzle N-3. "
     "Moisture ingress evident; metal loss confirmed by follow-up UT.",
     "Major", "OISD-STD-116 Cl. 7.9",
     "Strip insulation over affected zone, carry out 100% UT scan, repair per API 510 and reinstate weatherproofing."),

    ("Pitting observed on internal shell surface at liquid/vapour interface. "
     "Maximum pit depth measured 1.8 mm against nominal 12 mm wall.",
     "Major", "API 510 Cl. 5.4.2",
     "Perform pit depth mapping. Evaluate fitness-for-service per API 579 Level 1 before returning to service."),

    ("Insulation cladding damaged and displaced over a 2 m section of the vapour line. "
     "No metal loss detected at this stage.",
     "Minor", "OISD-STD-118 Cl. 6.2",
     "Reinstate cladding and seal joints to prevent water ingress."),

    ("Weld seam W-12 shows surface-breaking linear indication approximately 35 mm in length, "
     "confirmed by MPI. Indication is transverse to the weld axis.",
     "Critical", "ASME Sec. VIII Div. 1 UW-51",
     "Do not return to service. Excavate defect, re-weld per approved WPS and re-examine by RT. Notify Inspection Head immediately."),

    ("Nozzle N-1 internal projection shows erosion-corrosion consistent with high velocity "
     "impingement. Wall thickness reduced below nominal at 3 o'clock position.",
     "Major", "API 510 Cl. 7.2",
     "Install impingement plate. Increase UT monitoring frequency to 6-monthly at CML-04."),

    ("Support saddle anchor bolt at south-west location found loose. No structural distress observed.",
     "Observation", "OISD-STD-118 Cl. 6.5",
     "Re-torque anchor bolt to specification and record in maintenance log."),

    ("Pressure relief valve PSV-tag due for overhaul; last test certificate exceeds the "
     "36 month interval permitted for this service category.",
     "Major", "OISD-STD-132 Cl. 5.6",
     "Withdraw PSV for bench testing and overhaul prior to unit restart. Fit tested spare."),

    ("Minor external scaling and paint chalking on head section. No measurable metal loss.",
     "Observation", "OISD-STD-116 Cl. 7.3",
     "Include in routine painting schedule. No immediate action required."),

    ("Ladder and platform grating adjacent to manway found corroded with section loss "
     "exceeding 20% at two treads.",
     "Minor", "OISD-STD-118 Cl. 8.4",
     "Replace affected grating sections before next internal inspection."),
]

INSPECTOR_NAMES = [
    "R. Venkataraman", "S. Prakash Nayak", "A. Deshpande", "M. Fernandes",
    "K. Subramanian", "P. Bhat", "N. Kulkarni", "T. Rajagopal",
]

CML_LOCATIONS = [
    "Shell course 1 — 0°", "Shell course 1 — 90°", "Shell course 2 — 180°",
    "Shell course 2 — 270°", "Top head — crown", "Bottom head — knuckle",
    "Nozzle N-1 neck", "Nozzle N-3 neck", "Shell/head weld seam",
]


def _tag(prefix: str, rng: random.Random) -> str:
    return f"{prefix}-{rng.randint(1, 6)}{rng.randint(100, 999)}"


ROUTINE_POOL = [f for f in FINDING_POOL if f[1] in ("Observation", "Minor")]
SERIOUS_POOL = [f for f in FINDING_POOL if f[1] in ("Major", "Critical")]


def _pick_findings(
    rng: random.Random, want_serious: bool
) -> list[tuple[str, str, str, str]]:
    """Draw 2-5 findings, controlling whether any is Major/Critical."""
    n = rng.randint(2, 5)
    if not want_serious:
        # Routine pool is small; cap n so sampling stays valid.
        return rng.sample(ROUTINE_POOL, min(n, len(ROUTINE_POOL)))
    serious = rng.sample(SERIOUS_POOL, 1)
    rest = [f for f in FINDING_POOL if f not in serious]
    picked = serious + rng.sample(rest, min(n - 1, len(rest)))
    rng.shuffle(picked)
    return picked


def generate_report(
    seed: int,
    escalate: bool | None = None,
    trigger: str | None = None,
    summary_leaks: bool = True,
) -> InspectionReport:
    """Generate one deterministic, realistic inspection report.

    Args:
        seed: makes the report reproducible.
        escalate: force the report to require approval (True), be routine
            (False), or let chance decide (None). Balancing this matters --
            an unbalanced corpus lets a model score well by always guessing
            the majority class.
        trigger: when escalate=True, what causes it -- "severity",
            "thickness_only", or "both". "thickness_only" is the interesting
            case: the findings table looks routine and only the UT survey
            reveals the problem, so an agent that reads one table fails it.
        summary_leaks: whether the inspector's summary states the conclusion.
            True makes the task easy (read one sentence); False forces the
            agent to derive it from the tables. Vary this across the corpus so
            both are measured -- a score on leaking summaries alone would
            badly overstate real capability.
    """
    rng = random.Random(seed)

    if escalate is None:
        want_serious = rng.random() < 0.5
        force_breach = rng.random() < 0.35
    elif escalate is False:
        want_serious, force_breach = False, False
    else:
        trigger = trigger or rng.choice(["severity", "thickness_only", "both"])
        want_serious = trigger in ("severity", "both")
        force_breach = trigger in ("thickness_only", "both")

    prefix, equip_name, _kind = rng.choice(EQUIPMENT)
    unit_code, unit_name = rng.choice(UNITS)
    tag = _tag(prefix, rng)

    insp_date = date(2026, 1, 1) + timedelta(days=rng.randint(0, 240))
    next_due = insp_date + timedelta(days=rng.choice([365, 730, 1095]))

    findings_raw = _pick_findings(rng, want_serious)
    findings = [
        Finding(
            finding_id=f"F-{i + 1:02d}",
            location=rng.choice(CML_LOCATIONS),
            description=desc,
            severity=sev,
            ref_clause=clause,
            recommendation=rec,
        )
        for i, (desc, sev, clause, rec) in enumerate(findings_raw)
    ]

    # Thickness readings. One CML is driven below minimum where the requested
    # escalation trigger calls for it, so the agent has a hard numeric fact to
    # catch. Breach position varies so it is never always the same row.
    nominal = rng.choice([10.0, 12.0, 14.0, 16.0, 20.0])
    min_req = round(nominal * rng.uniform(0.55, 0.70), 1)

    cml_locs = rng.sample(CML_LOCATIONS, rng.randint(4, 6))
    breach_at = rng.randint(1, len(cml_locs)) if force_breach else None

    readings: list[ThicknessReading] = []
    for i, loc in enumerate(cml_locs, start=1):
        previous = round(nominal - rng.uniform(0.2, 1.8), 2)
        if i == breach_at:
            current = round(min_req - rng.uniform(0.1, 0.5), 2)
        else:
            # Keep non-breach rows comfortably clear of the limit, otherwise
            # random drift can create an unintended breach in a "routine" report.
            current = round(max(previous - rng.uniform(0.05, 0.45),
                                min_req + 0.15), 2)
        readings.append(
            ThicknessReading(
                cml_id=f"CML-{i:02d}",
                location=loc,
                nominal_mm=nominal,
                previous_mm=previous,
                current_mm=current,
                min_required_mm=min_req,
            )
        )

    corrosion_rate = round(rng.uniform(0.05, 0.42), 3)
    thinnest = min(r.current_mm for r in readings)
    remaining_life = round(max((thinnest - min_req) / corrosion_rate, 0.0), 1)

    report = InspectionReport(
        report_no=f"MRPL/INSP/{insp_date.year}/{rng.randint(1000, 9999)}",
        equipment_tag=tag,
        equipment_name=equip_name,
        unit=f"{unit_code} — {unit_name}",
        plant=rng.choice(PLANTS),
        inspection_type=rng.choice(INSPECTION_TYPES),
        inspection_date=insp_date.strftime("%d-%m-%Y"),
        next_due_date=next_due.strftime("%d-%m-%Y"),
        inspector_name=rng.choice(INSPECTOR_NAMES),
        inspector_cert=f"API-510-{rng.randint(10000, 99999)}",
        design_pressure_barg=round(rng.uniform(3.5, 42.0), 1),
        design_temp_c=rng.choice([120, 180, 250, 320, 380, 420]),
        service_fluid=rng.choice(SERVICE_FLUIDS),
        year_built=rng.randint(1987, 2016),
        corrosion_rate_mm_yr=corrosion_rate,
        remaining_life_yr=remaining_life,
        findings=findings,
        readings=readings,
    )

    report.summary_leaks_conclusion = summary_leaks
    breached = report.breached_cmls
    head = (
        f"{report.inspection_type} of {tag} ({equip_name}) completed on "
        f"{report.inspection_date}. {len(findings)} finding(s) recorded. "
    )
    tail = (
        f"Calculated corrosion rate {corrosion_rate} mm/yr, estimated remaining "
        f"life {remaining_life} years."
    )

    if summary_leaks:
        verdict = f"Highest severity {report.highest_severity}. " + (
            f"Thickness at {', '.join(breached)} is below the minimum required "
            f"{min_req} mm and requires fitness-for-service evaluation before "
            f"continued operation. "
            if breached
            else "All CML readings remain above minimum required thickness. "
        )
    else:
        # Neutral wording -- realistic for a terse inspector, and it forces the
        # verdict to be derived from the tables rather than read off a sentence.
        verdict = (
            "Findings and UT survey results are tabulated above. "
            "Refer Sections 2 and 3 for details. "
        )

    report.summary = head + verdict + tail
    return report
