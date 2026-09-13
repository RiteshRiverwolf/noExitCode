"""The synthetic reference library: procedures, a clause register, and memos.

Written for SIH26117 so the knowledge base has documents with real structure
and genuine cross-references to retrieve from (docs/DATASETS.md, Part 1.1).

Rules this content follows -- they are what make it safe to put in front of
refinery engineers:

  * **Nothing here is the text of any OISD, API or ASME standard.** OISD
    publications may not be reproduced (DATASETS.md section 2.3), and a
    librarian quoting invented words as if they were a real standard would
    mislead the people it is for. The procedures REFER to clauses by number;
    the register says where each clause is applied, and states that it does not
    reproduce the clause.
  * **Nothing here is an MRPL document.** Every page carries FOOTER.
  * **It agrees with the rest of the workbench.** The severity grades and
    escalation triggers are the rules engine's (workbench/rules.py); the
    half-life rule and the corrosion-rate formula are the coding tasks'
    (workbench/coding_tasks.py); and each of the nine clauses the corpus reports
    cite (bench/corpus/content.py) is covered, with the grade and action the
    corpus gives it.

QUESTIONS is the retrieval test set: questions with the sections that answer
them and a fact a correct answer must contain -- including ones that need two
documents -- and questions the library cannot answer, where the only right
response is to say so.
"""

FOOTER = ("SYNTHETIC TEST DOCUMENT written for SIH26117. Not an MRPL document. "
          "Does not reproduce any OISD, API or ASME standard.")

DOCUMENTS = [
    {
        "doc_id": "SOP-INSP-001",
        "kind": "procedure",
        "title": "Static Equipment Inspection Programme: Roles, Grades and Escalation",
        "issued": "01-04-2024",
        "sections": [
            {"id": "1", "title": "Purpose and scope",
             "text": "This procedure sets out who inspects static equipment, how findings are graded, "
                     "and when a finding must be escalated. It applies to pressure vessels, columns, heat "
                     "exchangers and process piping in all refinery units. Rotating equipment is outside its "
                     "scope and is not covered by any procedure in this library."},
            {"id": "2", "title": "Roles and authority",
             "text": "Inspections are carried out by an Inspector holding a current API 510 or API 570 "
                     "certificate. The Senior Inspection Engineer reviews every inspection report within 3 "
                     "working days of receipt.\n\n"
                     "Only the Head of the Inspection Department may approve continued operation of equipment "
                     "for which an escalation trigger has fired. When the Head is absent this authority may be "
                     "delegated to a Senior Inspection Engineer, never lower, and only in writing. A written "
                     "delegation states its start and end dates."},
            {"id": "3", "title": "Severity grades",
             "text": "Every finding is given exactly one of four grades.\n\n"
                     "Critical: a threat to containment or to life. The equipment is isolated or is not returned "
                     "to service, and the Head of the Inspection Department is notified within 1 hour.\n\n"
                     "Major: degradation that may breach a design limit before the next inspection is due. An "
                     "engineering review is completed within 7 days.\n\n"
                     "Minor: no effect on integrity before the next inspection is due. Action is taken at the "
                     "next available shutdown.\n\n"
                     "Observation: recorded for trending. No action is required."},
            {"id": "4", "title": "Escalation triggers",
             "text": "An inspection report is escalated for engineering review when any of the following is "
                     "true: a finding is graded Major or Critical; the current thickness at any condition "
                     "monitoring location is below its minimum required thickness, evaluated as set out in "
                     "SOP-INSP-003 section 4; or a critical value is missing or unreadable. A missing or "
                     "unreadable value is re-measured or confirmed by a person. It is never estimated.\n\n"
                     "A report that triggers none of these has not been declared fit for service. Only a "
                     "signed approval note does that."},
            {"id": "5", "title": "Approval notes",
             "text": "Escalated reports are summarised in an approval note prepared as set out in "
                     "SOP-INSP-006. Approval notes are numbered AN/report number/D followed by the revision "
                     "number, starting at D0."},
        ],
    },
    {
        "doc_id": "SOP-INSP-002",
        "kind": "procedure",
        "title": "Inspection Intervals and Due Dates",
        "issued": "01-04-2024",
        "sections": [
            {"id": "1", "title": "Purpose and scope",
             "text": "This procedure sets the longest time allowed between inspections of static equipment, "
                     "and how the next due date is calculated."},
            {"id": "2", "title": "Maximum intervals",
             "text": "External visual inspection of a pressure vessel is carried out at least every 5 years. "
                     "Internal inspection is carried out at least every 10 years, or at half the remaining "
                     "life if that is sooner. On-stream ultrasonic inspection may replace an internal "
                     "inspection only where internal access is not possible, and only with the written "
                     "approval of the Head of the Inspection Department."},
            {"id": "3", "title": "The half-life rule",
             "text": "The interval to the next inspection is half of the calculated remaining life, rounded "
                     "down to a whole number of years. It is never less than 1 year and never more than the "
                     "maximum interval in section 2. Remaining life is calculated as set out in SOP-INSP-003 "
                     "section 5.\n\n"
                     "Example: a remaining life of 7.9 years gives 3.95 years, which is rounded down to an "
                     "interval of 3 years."},
            {"id": "4", "title": "Equipment with no remaining life",
             "text": "Where the calculated remaining life is zero or less, the equipment is due for inspection "
                     "immediately. The Head of the Inspection Department is informed within 24 hours. Continued "
                     "operation requires an approval note under SOP-INSP-006 supported by a fitness-for-service "
                     "assessment under SOP-INSP-005 section 5."},
            {"id": "5", "title": "Increased monitoring after erosion-corrosion",
             "text": "Where erosion-corrosion is found at a nozzle, the affected condition monitoring location "
                     "is surveyed by ultrasonic thickness measurement every 6 months until two consecutive "
                     "surveys show a stable corrosion rate. This applies API 510 Cl. 7.2; the code itself "
                     "governs the interval requirements."},
            {"id": "6", "title": "Changing an interval",
             "text": "An interval longer than the maximum in section 2 requires a Management of Change form "
                     "MOC-07 approved by the Head of the Inspection Department."},
        ],
    },
    {
        "doc_id": "SOP-INSP-003",
        "kind": "procedure",
        "title": "Ultrasonic Thickness Survey",
        "issued": "01-04-2024",
        "sections": [
            {"id": "1", "title": "Purpose and scope",
             "text": "This procedure covers ultrasonic measurement of wall thickness at condition monitoring "
                     "locations, and how the readings are evaluated."},
            {"id": "2", "title": "Instrument calibration",
             "text": "The thickness gauge is calibrated on a stepped reference block before each survey and "
                     "again after every 4 hours of use. Each calibration is recorded on form UT-CAL-02. "
                     "Readings taken with a gauge that has drifted out of calibration are void and are taken "
                     "again. The interval was reduced from 8 hours to 4 hours by memo MEMO-2025-014."},
            {"id": "3", "title": "Condition monitoring locations",
             "text": "At each condition monitoring location four readings are taken, at 0, 90, 180 and 270 "
                     "degrees, and the lowest is recorded. At nozzles a 50 mm grid is used. Location "
                     "identifiers are never renumbered between surveys, so that readings can be compared over "
                     "time."},
            {"id": "4", "title": "Evaluating a reading",
             "text": "The current thickness is compared with the minimum required thickness stated in the "
                     "equipment's design record. A current thickness below the minimum is an escalation "
                     "trigger under SOP-INSP-001 section 4, and is confirmed by a repeat reading within 24 "
                     "hours. Readings are recorded to two decimal places."},
            {"id": "5", "title": "Corrosion rate and remaining life",
             "text": "The corrosion rate is the previous thickness minus the current thickness, divided by the "
                     "number of years between the two surveys. The remaining life is the current thickness "
                     "minus the minimum required thickness, divided by the corrosion rate.\n\n"
                     "If the corrosion rate is zero or negative, no remaining life is calculated. A thickness "
                     "that has increased since the previous survey points to a measurement error or to a "
                     "repair that was not recorded, and is referred to the Senior Inspection Engineer."},
            {"id": "6", "title": "Doubtful readings",
             "text": "A reading with an unreadable or doubtful digit is measured again. A value is never "
                     "estimated, rounded up, or copied from a previous survey."},
        ],
    },
    {
        "doc_id": "SOP-INSP-004",
        "kind": "procedure",
        "title": "External Corrosion, Coatings and Insulation",
        "issued": "01-04-2024",
        "sections": [
            {"id": "1", "title": "Purpose and scope",
             "text": "This procedure covers corrosion on the outside of equipment, the condition of protective "
                     "coatings, and damage beneath and to thermal insulation."},
            {"id": "2", "title": "Coating breakdown and external corrosion",
             "text": "Localised coating breakdown with rust scaling, where no measurable metal loss is found, "
                     "is graded Minor. The surface is prepared to St-3 and recoated with an approved coating "
                     "system at the next available shutdown. This applies OISD-STD-116 Cl. 7.3."},
            {"id": "3", "title": "Scaling and paint chalking",
             "text": "External scaling or chalking of paint with no measurable metal loss is graded Observation "
                     "and is added to the routine painting schedule. This also applies OISD-STD-116 Cl. 7.3."},
            {"id": "4", "title": "Corrosion under insulation",
             "text": "Insulation terminations, nozzles and supports are the most likely places for corrosion "
                     "under insulation. Where moisture has entered the insulation, the insulation is stripped "
                     "over the affected zone and the exposed surface is scanned by ultrasonic thickness "
                     "measurement over its full area, using the method in SOP-INSP-003 section 3. Confirmed "
                     "metal loss under insulation is graded at least Major. This applies OISD-STD-116 Cl. 7.9."},
            {"id": "5", "title": "Damaged insulation cladding",
             "text": "Damaged or displaced insulation cladding with no metal loss is graded Minor. The cladding "
                     "is reinstated and its joints sealed to keep water out, because damaged cladding is the "
                     "most common way water reaches the metal under insulation (section 4). This applies "
                     "OISD-STD-118 Cl. 6.2."},
        ],
    },
    {
        "doc_id": "SOP-INSP-005",
        "kind": "procedure",
        "title": "Internal Damage, Weld Defects and Fitness-for-Service",
        "issued": "01-04-2024",
        "sections": [
            {"id": "1", "title": "Purpose and scope",
             "text": "This procedure covers damage found inside equipment and in welds, and when a "
                     "fitness-for-service assessment is needed before equipment returns to service."},
            {"id": "2", "title": "Pitting",
             "text": "The maximum pit depth is measured with a pit gauge and pit depths are mapped over the "
                     "affected area. Where the deepest pit exceeds 10 percent of the nominal wall thickness, "
                     "the finding is graded Major and a fitness-for-service assessment is completed before "
                     "the equipment returns to service. This applies API 510 Cl. 5.4.2, with the assessment "
                     "made to API 579 Level 1."},
            {"id": "3", "title": "Erosion-corrosion at nozzles",
             "text": "Erosion-corrosion caused by high-velocity impingement at internal nozzle projections is "
                     "addressed by fitting an impingement plate. The location is then monitored as set out in "
                     "SOP-INSP-002 section 5."},
            {"id": "4", "title": "Weld defects",
             "text": "A surface-breaking linear indication in a weld, confirmed by magnetic particle "
                     "inspection, is graded Critical. The equipment is not returned to service. The defect is "
                     "excavated, re-welded to an approved welding procedure specification, and examined again "
                     "by radiography. Acceptance is judged against ASME Sec. VIII Div. 1 UW-51 where that is "
                     "the equipment's construction code. The Head of the Inspection Department is notified as "
                     "a Critical finding requires under SOP-INSP-001 section 3."},
            {"id": "5", "title": "Fitness-for-service assessments",
             "text": "Fitness-for-service assessments are made by a Senior Inspection Engineer or by a "
                     "qualified consultant appointed by the Head of the Inspection Department. The assessment "
                     "report is attached to the approval note, as SOP-INSP-006 section 3 requires."},
        ],
    },
    {
        "doc_id": "SOP-INSP-006",
        "kind": "procedure",
        "title": "Approval Notes",
        "issued": "01-04-2024",
        "sections": [
            {"id": "1", "title": "Purpose and scope",
             "text": "This procedure sets out what an approval note for an escalated inspection report must "
                     "contain, and how it is drafted, signed and revised."},
            {"id": "2", "title": "Content",
             "text": "Every approval note states: the outcome of the escalation rules and the reason for it; "
                     "every finding with its grade; every thickness reading with its current and minimum "
                     "required values; the number of the source inspection report; and a record of how the "
                     "note was checked."},
            {"id": "3", "title": "Evidence",
             "text": "Every critical value in an approval note can be traced to the page of the source report "
                     "it came from. Where a value was read from a scanned document, the note includes an image "
                     "of the cell the value was read from. Any fitness-for-service assessment is attached."},
            {"id": "4", "title": "Drafts and signature",
             "text": "A draft carries the word DRAFT on every page. A draft must not contain the words approved "
                     "or fit for service: only a person decides that. Only the Head of the Inspection "
                     "Department, or a Senior Inspection Engineer holding a written delegation under "
                     "SOP-INSP-001 section 2, signs an approval note."},
            {"id": "5", "title": "Revisions",
             "text": "A signed approval note is never edited. A correction is issued as a new revision, "
                     "numbered one higher, which names the revision it replaces."},
        ],
    },
    {
        "doc_id": "SOP-INSP-007",
        "kind": "procedure",
        "title": "Pressure Relief Devices",
        "issued": "01-04-2024",
        "sections": [
            {"id": "1", "title": "Purpose and scope",
             "text": "This procedure covers the testing and overhaul of pressure safety valves."},
            {"id": "2", "title": "Test intervals",
             "text": "A pressure safety valve in general hydrocarbon service is bench tested and overhauled at "
                     "intervals of no more than 36 months. In fouling or corrosive service the interval is no "
                     "more than 24 months. This applies OISD-STD-132 Cl. 5.6."},
            {"id": "3", "title": "Overdue devices",
             "text": "A pressure safety valve past its test interval is a Major finding. It is withdrawn for "
                     "bench testing and overhaul before the unit restarts, and a tested spare is fitted in its "
                     "place."},
            {"id": "4", "title": "Records",
             "text": "Each test certificate is kept on the valve's history card, with the set pressure and the "
                     "date of the test."},
        ],
    },
    {
        "doc_id": "SOP-INSP-008",
        "kind": "procedure",
        "title": "Structures, Supports and Access",
        "issued": "01-04-2024",
        "sections": [
            {"id": "1", "title": "Purpose and scope",
             "text": "This procedure covers equipment supports, anchor bolts, ladders, platforms and "
                     "fireproofing."},
            {"id": "2", "title": "Anchor bolts and saddles",
             "text": "A loose anchor bolt with no sign of structural distress is graded Observation. The bolt "
                     "is re-torqued to specification and the work recorded in the maintenance log. This "
                     "applies OISD-STD-118 Cl. 6.5."},
            {"id": "3", "title": "Ladders, platforms and grating",
             "text": "Section loss of more than 20 percent on any ladder tread or grating panel is graded Minor, "
                     "and the affected parts are replaced before the next internal inspection. Section loss of "
                     "more than 40 percent, or any failed fixing, is graded Major, and the access is closed "
                     "until it is repaired. This applies OISD-STD-118 Cl. 8.4."},
            {"id": "4", "title": "Fireproofing",
             "text": "Cracked or spalled fireproofing on supports is recorded and assessed at the next "
                     "turnaround."},
        ],
    },
    {
        "doc_id": "SOP-REG-001",
        "kind": "register",
        "title": "Clause Cross-Reference Register",
        "issued": "01-04-2024",
        "sections": [
            {"id": "1", "title": "How to read this register",
             "text": "This register lists where each external clause cited in inspection reports is applied "
                     "in these procedures. It does not reproduce any clause. The standard or code itself "
                     "governs, and must be consulted in its current edition."},
            {"id": "2", "title": "Register",
             "text": "Each clause below is applied in the procedure section named beside it.",
             "table": [
                 ("OISD-STD-116 Cl. 7.3", "SOP-INSP-004 sections 2 and 3", "external corrosion, coatings, scaling"),
                 ("OISD-STD-116 Cl. 7.9", "SOP-INSP-004 section 4", "corrosion under insulation"),
                 ("OISD-STD-118 Cl. 6.2", "SOP-INSP-004 section 5", "insulation cladding"),
                 ("OISD-STD-118 Cl. 6.5", "SOP-INSP-008 section 2", "anchor bolts and saddles"),
                 ("OISD-STD-118 Cl. 8.4", "SOP-INSP-008 section 3", "ladders, platforms, grating"),
                 ("OISD-STD-132 Cl. 5.6", "SOP-INSP-007 section 2", "pressure safety valve test intervals"),
                 ("API 510 Cl. 5.4.2", "SOP-INSP-005 section 2", "pitting"),
                 ("API 510 Cl. 7.2", "SOP-INSP-002 section 5", "monitoring after erosion-corrosion"),
                 ("ASME Sec. VIII Div. 1 UW-51", "SOP-INSP-005 section 4", "weld defects"),
             ]},
        ],
    },
    {
        "doc_id": "MEMO-2025-014",
        "kind": "memo",
        "title": "Change to ultrasonic gauge calibration interval",
        "issued": "24-02-2025",
        "memo": {"to": "All Inspectors", "from": "Head of the Inspection Department",
                 "date": "24-02-2025"},
        "sections": [
            {"id": "1", "title": "Change to ultrasonic gauge calibration interval",
             "text": "From 1 March 2025 thickness gauges are checked on the stepped reference block every 4 "
                     "hours of use instead of every 8 hours. During the January 2025 survey of the crude unit, "
                     "two gauges were found to have drifted by up to 0.15 mm between calibrations, enough to "
                     "move a reading across its minimum. SOP-INSP-003 section 2 has been revised to match."},
        ],
    },
    {
        "doc_id": "MEMO-2026-003",
        "kind": "memo",
        "title": "Delegation of signing authority during the 2026 turnaround",
        "issued": "12-01-2026",
        "memo": {"to": "Inspection Department; Unit Managers", "from": "Head of the Inspection Department",
                 "date": "12-01-2026"},
        "sections": [
            {"id": "1", "title": "Delegation of signing authority during the 2026 turnaround",
             "text": "From 15 January 2026 to 28 February 2026, while I am on site with the turnaround team, "
                     "Senior Inspection Engineer R. Menon may sign approval notes on my behalf. This is a "
                     "written delegation under SOP-INSP-001 section 2. Approval notes for any Critical finding "
                     "are not covered by this delegation and remain with me."},
        ],
    },
]

# expect: the answer is in any one of these (document, section) pairs -- a
# question counts as found if at least one is retrieved. must_contain: facts a
# correct answer states -- an entry that is a list means any one of its wordings.
# needs: pairs that must ALL be retrieved (multi-hop). set: "held-out" questions
# were written after a result was seen and are never used to tune anything.
QUESTIONS = [
    {"id": "Q01", "question": "Which procedure applies OISD-STD-118 Cl. 6.2?",
     "expect": [("SOP-REG-001", "2"), ("SOP-INSP-004", "5")], "must_contain": ["SOP-INSP-004"]},
    {"id": "Q02", "question": "What grade is damaged insulation cladding when there is no metal loss?",
     "expect": [("SOP-INSP-004", "5")], "must_contain": ["Minor"]},
    {"id": "Q03", "question": "How often must the ultrasonic thickness gauge be calibrated during a survey?",
     "expect": [("SOP-INSP-003", "2"), ("MEMO-2025-014", "1")], "must_contain": ["4 hours"]},
    {"id": "Q04", "question": "Why was the calibration interval for thickness gauges shortened?",
     "expect": [("MEMO-2025-014", "1")], "must_contain": ["drift"]},
    {"id": "Q05", "question": "How is the interval to the next inspection worked out from the remaining life?",
     "expect": [("SOP-INSP-002", "3")], "must_contain": ["half", "rounded down"]},
    {"id": "Q06", "question": "What is the longest test interval for a pressure safety valve in hydrocarbon service?",
     "expect": [("SOP-INSP-007", "2")], "must_contain": ["36 months"]},
    {"id": "Q07", "question": "What should happen if a thickness reading is higher than at the previous survey?",
     "expect": [("SOP-INSP-003", "5")], "must_contain": ["Senior Inspection Engineer"]},
    {"id": "Q08", "question": "At what pit depth does pitting become a Major finding?",
     "expect": [("SOP-INSP-005", "2")], "must_contain": ["10 percent"]},
    {"id": "Q09", "question": "Who could sign an approval note for a Major finding on 10 February 2026?",
     "expect": [("MEMO-2026-003", "1")], "needs": [("MEMO-2026-003", "1"), ("SOP-INSP-001", "2")],
     "must_contain": ["Menon"]},
    # must_contain widened to equivalent wordings on 2026-09-13, after granite answered
    # "cannot say the equipment is fit for service" -- correct, but not the words "must not".
    {"id": "Q10", "question": "Can a draft approval note say the equipment is fit for service?",
     "expect": [("SOP-INSP-006", "4")], "must_contain": [["must not", "cannot", "may not"]]},
    {"id": "Q11", "question": "How much section loss on platform grating makes it a Major finding?",
     "expect": [("SOP-INSP-008", "3")], "must_contain": ["40 percent"]},
    {"id": "Q12", "question": "Where is API 510 Cl. 7.2 applied in our procedures, and what does it require us to do?",
     "expect": [("SOP-REG-001", "2"), ("SOP-INSP-002", "5")], "needs": [("SOP-INSP-002", "5")],
     "must_contain": ["6 months"]},
    {"id": "Q13", "question": "Who could sign an approval note for a Critical weld defect on 10 February 2026?",
     "expect": [("MEMO-2026-003", "1")], "needs": [("MEMO-2026-003", "1")],
     "must_contain": ["Head of the Inspection Department"]},

    # The real CSB report (public domain): a messy, 132-page document, not written for us.
    {"id": "C01", "question": "How many people sought medical treatment after the Chevron Richmond pipe rupture?",
     "expect_pages": [("CSB-CHEVRON-RICHMOND", 12)], "must_contain": ["15,000"]},
    {"id": "C02", "question": "Which piping specification requires a minimum silicon content, according to the CSB?",
     "expect_pages": [("CSB-CHEVRON-RICHMOND", 16)], "must_contain": ["A106"]},
    {"id": "C03", "question": "What inspection of the 4-sidecut piping did Chevron recommend internally but not carry out?",
     "expect_pages": [("CSB-CHEVRON-RICHMOND", 17), ("CSB-CHEVRON-RICHMOND", 18)],
     "must_contain": ["100 percent component inspection"]},
    {"id": "C04", "question": "Why does the silicon content of carbon steel piping matter for sulfidation corrosion?",
     "expect_pages": [("CSB-CHEVRON-RICHMOND", 15), ("CSB-CHEVRON-RICHMOND", 16)], "must_contain": ["silicon"]},

    {"id": "U01", "question": "What is the inspection interval for centrifugal compressors?",
     "answerable": False, "why": "rotating equipment is outside every procedure in the library"},
    {"id": "U02", "question": "What does OISD-STD-116 Cl. 7.3 say, word for word?",
     "answerable": False, "why": "the library refers to clauses but never reproduces them"},
    {"id": "U03", "question": "What is the name of the Head of the Inspection Department?",
     "answerable": False, "why": "no document names the Head"},
    {"id": "U04", "question": "Which coating product is approved for surfaces prepared to St-3?",
     "answerable": False, "why": "the procedures say an approved coating system, without naming one"},
    {"id": "U05", "question": "What minimum thickness does an API 579 Level 2 assessment require for a 20 mm shell?",
     "answerable": False, "why": "the library does not contain API 579 or any such calculation"},

    # HELD-OUT, written 2026-09-13 after the first Librarian run and BEFORE any change was
    # tested: the same traps on different content. Scored separately; never used to tune.
    {"id": "H01", "set": "held-out", "question": "Which procedure section applies OISD-STD-116 Cl. 7.9?",
     "expect": [("SOP-REG-001", "2"), ("SOP-INSP-004", "4")], "must_contain": ["SOP-INSP-004"]},
    {"id": "H02", "set": "held-out", "question": "Quote the exact text of OISD-STD-132 Cl. 5.6.",
     "answerable": False, "why": "the library applies the clause (SOP-INSP-007 section 2) but never reproduces it"},
    {"id": "H03", "set": "held-out", "question": "Who could sign an approval note for a Minor finding on 20 January 2026?",
     "expect": [("MEMO-2026-003", "1")], "needs": [("MEMO-2026-003", "1")], "must_contain": ["Menon"]},
    {"id": "H04", "set": "held-out", "question": "What is R. Sharma's inspector certificate number?",
     "answerable": False, "why": "no document names R. Sharma or gives any certificate number"},
    {"id": "H05", "set": "held-out", "question": "Is a pressure safety valve in fouling or corrosive service tested every 12 months?",
     "expect": [("SOP-INSP-007", "2")], "must_contain": ["24 months"]},
    {"id": "H06", "set": "held-out", "question": "To what torque value is a loose anchor bolt re-torqued?",
     "answerable": False, "why": "the procedure says re-torqued to specification, without a value"},
    {"id": "H07", "set": "held-out", "question": "At what time was the shelter-in-place advisory lifted after the Chevron Richmond fire?",
     "expect_pages": [("CSB-CHEVRON-RICHMOND", 11), ("CSB-CHEVRON-RICHMOND", 12)], "must_contain": ["11:12"]},
    {"id": "H08", "set": "held-out", "question": "According to the CSB, where did the figure for people who sought medical treatment come from?",
     "expect_pages": [("CSB-CHEVRON-RICHMOND", 12)], "must_contain": ["local hospitals"]},
]
