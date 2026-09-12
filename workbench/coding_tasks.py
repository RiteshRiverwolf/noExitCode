"""Coding tasks for the Coder agent, each with acceptance tests the model never sees.

Kept apart from `coder.py` so the tasks read as a spec: what the model is
asked for on the left, what has to be true on the right.

Both tasks are real work from this workbench rather than puzzle questions. The
first answers something no single inspection report contains -- which is the
point of giving an agent the ability to write code: "read all of these and tell
me which readings are worst" is miserable for a language model to do in its
head and trivial for ten lines of Python, and the ten lines can be shown,
re-run and checked.

Acceptance tests are written against the CONTRACT in the brief, and cover the
cases a first draft usually gets wrong:
  - a value exactly at the minimum is not below it;
  - rows with a missing value are skipped, not guessed;
  - ties are ordered predictably;
  - thickness that grew since the last inspection gives no remaining life,
    rather than a negative or infinite one.
"""

from __future__ import annotations

from workbench.coder import CodingTask

# --- task 1: which readings are below their minimum, across many reports ------

CML_BRIEF = """Write a file `solution.py` for an offline inspection workbench.

It must define one function:

    below_minimum(readings) -> list[dict]

`readings` is a list of dicts, each with these keys:
    report            str, e.g. "MRPL/INSP/2026/8013"
    cml_id            str, e.g. "CML-03"
    current_mm        float or None   (the measured thickness)
    min_required_mm   float or None   (the minimum allowed)

Return one dict for every reading whose current thickness is BELOW its minimum:

    {"report": <report>, "cml_id": <cml_id>, "shortfall_mm": <float>}

Rules, exactly:
  * "below" means strictly less than. A reading equal to the minimum is NOT below it.
  * shortfall_mm = min_required_mm - current_mm, rounded to 2 decimal places.
  * If current_mm or min_required_mm is None, skip that reading entirely -- never
    guess a missing value.
  * Sort the result by shortfall_mm from largest to smallest. Where two shortfalls
    are equal, order those by cml_id alphabetically (ascending).
  * Return an empty list if nothing is below its minimum.

Do not print anything and do not read any files. Only define the function."""

CML_ACCEPTANCE = '''
"""Acceptance tests for below_minimum(). The model does not see this file."""
import sys

try:
    from solution import below_minimum
except Exception as e:
    print(f"could not import below_minimum from solution.py: {type(e).__name__}: {e}")
    sys.exit(1)

failures = []

def check(name, got, want):
    if got != want:
        failures.append(f"{name}\\n     got:  {got}\\n     want: {want}")

# 1. the ordinary case, and the ordering
rows = [
    {"report": "R1", "cml_id": "CML-01", "current_mm": 19.28, "min_required_mm": 12.7},
    {"report": "R1", "cml_id": "CML-03", "current_mm": 12.32, "min_required_mm": 12.7},
    {"report": "R2", "cml_id": "CML-02", "current_mm": 8.10, "min_required_mm": 10.0},
]
check("below_minimum orders by shortfall, largest first", below_minimum(rows), [
    {"report": "R2", "cml_id": "CML-02", "shortfall_mm": 1.9},
    {"report": "R1", "cml_id": "CML-03", "shortfall_mm": 0.38},
])

# 2. exactly at the minimum is not below it
check("a reading equal to the minimum is not below it",
      below_minimum([{"report": "R1", "cml_id": "CML-09",
                      "current_mm": 12.7, "min_required_mm": 12.7}]), [])

# 3. a missing value is skipped, never guessed
mixed = [
    {"report": "R1", "cml_id": "CML-04", "current_mm": None, "min_required_mm": 12.7},
    {"report": "R1", "cml_id": "CML-05", "current_mm": 11.0, "min_required_mm": None},
    {"report": "R1", "cml_id": "CML-06", "current_mm": 11.0, "min_required_mm": 12.0},
]
check("rows with a missing value are skipped", below_minimum(mixed),
      [{"report": "R1", "cml_id": "CML-06", "shortfall_mm": 1.0}])

# 4. equal shortfalls are ordered by cml_id
ties = [
    {"report": "R1", "cml_id": "CML-22", "current_mm": 9.0, "min_required_mm": 10.0},
    {"report": "R1", "cml_id": "CML-07", "current_mm": 4.0, "min_required_mm": 5.0},
    {"report": "R1", "cml_id": "CML-11", "current_mm": 1.0, "min_required_mm": 2.0},
]
check("equal shortfalls are ordered by cml_id", [r["cml_id"] for r in below_minimum(ties)],
      ["CML-07", "CML-11", "CML-22"])

# 5. nothing below the minimum
check("nothing below the minimum gives an empty list",
      below_minimum([{"report": "R1", "cml_id": "CML-01",
                      "current_mm": 20.0, "min_required_mm": 12.7}]), [])

# 6. the shortfall is rounded to 2 decimals
# (9.999 and not 10.005: 12.0 - 10.005 is 1.99499...e0 in binary floating point,
#  so round() gives 1.99 and the test would be about float noise, not rounding.)
check("the shortfall is rounded to 2 decimals",
      below_minimum([{"report": "R1", "cml_id": "CML-08",
                      "current_mm": 9.999, "min_required_mm": 12.0}])[0]["shortfall_mm"], 2.0)

# 7. an empty list in, an empty list out
check("an empty input gives an empty list", below_minimum([]), [])

if failures:
    print(f"{len(failures)} acceptance test(s) failed:\\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all 7 acceptance tests passed")
'''

# --- task 2: corrosion rate and remaining life --------------------------------

RATE_BRIEF = """Write a file `solution.py` for an offline inspection workbench.

It must define one function:

    remaining_life(previous_mm, current_mm, years_between, min_required_mm) -> dict

All four arguments are floats. Return a dict with exactly these two keys:

    {"corrosion_rate_mm_yr": <float>, "remaining_life_yr": <float or None>}

Rules, exactly:
  * corrosion_rate_mm_yr = (previous_mm - current_mm) / years_between,
    rounded to 3 decimal places.
  * remaining_life_yr = (current_mm - min_required_mm) / corrosion_rate_mm_yr,
    rounded to 1 decimal place, using the ROUNDED corrosion rate.
  * If the corrosion rate is zero or negative -- the metal did not get thinner --
    remaining_life_yr must be None. Do not return a negative or infinite life.
  * If the current thickness is already at or below the minimum,
    remaining_life_yr must be 0.0.
  * If years_between is zero or negative, raise ValueError.

Do not print anything and do not read any files. Only define the function."""

RATE_ACCEPTANCE = '''
"""Acceptance tests for remaining_life(). The model does not see this file."""
import sys

try:
    from solution import remaining_life
except Exception as e:
    print(f"could not import remaining_life from solution.py: {type(e).__name__}: {e}")
    sys.exit(1)

failures = []

def check(name, got, want):
    if got != want:
        failures.append(f"{name}\\n     got:  {got}\\n     want: {want}")

# 1. the ordinary case: 0.5 mm lost over 2 years, 3 mm of margin left
check("ordinary case", remaining_life(20.0, 19.5, 2.0, 16.5),
      {"corrosion_rate_mm_yr": 0.25, "remaining_life_yr": 12.0})

# 2. thickness unchanged -> no rate, so no remaining life
check("no metal loss gives no remaining life", remaining_life(20.0, 20.0, 2.0, 16.5),
      {"corrosion_rate_mm_yr": 0.0, "remaining_life_yr": None})

# 3. thickness GREW since the last reading (a misread or a repair) -> no life
got = remaining_life(19.0, 19.4, 2.0, 16.5)
check("thickness that grew gives no remaining life", got["remaining_life_yr"], None)
check("thickness that grew gives a negative rate", got["corrosion_rate_mm_yr"], -0.2)

# 4. already at or below the minimum -> zero, not negative
check("already below the minimum gives zero",
      remaining_life(20.0, 12.3, 2.0, 12.7)["remaining_life_yr"], 0.0)
check("exactly at the minimum gives zero",
      remaining_life(20.0, 12.7, 2.0, 12.7)["remaining_life_yr"], 0.0)

# 5. the rate is rounded to 3 decimals, and that rounded rate is what is used
got = remaining_life(20.0, 19.61, 3.0, 12.7)
check("the rate is rounded to 3 decimals", got["corrosion_rate_mm_yr"], 0.13)
check("the rounded rate is used for the life", got["remaining_life_yr"], 53.2)

# 6. a zero or negative interval is an error
for bad in (0.0, -1.0):
    try:
        remaining_life(20.0, 19.0, bad, 12.7)
        failures.append(f"years_between={bad} should raise ValueError, but returned a value")
    except ValueError:
        pass
    except Exception as e:
        failures.append(f"years_between={bad} should raise ValueError, raised {type(e).__name__}")

if failures:
    print(f"{len(failures)} acceptance test(s) failed:\\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all acceptance tests passed")
'''

# --- task 3: when is the next inspection due -----------------------------------
# Harder on purpose. The half-life rule is real API 510 practice, and the two
# things a first draft nearly always gets wrong -- rounding an interval DOWN
# rather than to nearest, and 29 February -- are exactly the kind of mistake
# that is invisible in a demo and expensive in a refinery.

DUE_BRIEF = """Write a file `solution.py` for an offline inspection workbench.

It must define one function:

    next_due_date(last_inspection, remaining_life_yr, max_interval_yr) -> str

    last_inspection    str, a date as "DD-MM-YYYY", e.g. "03-02-2026"
    remaining_life_yr  float, the estimated remaining life in years
    max_interval_yr    int, the longest interval the code allows

Return the next inspection due date, as a string in the same "DD-MM-YYYY" form.

Rules, exactly:
  * The interval is the HALF-LIFE rule: half of the remaining life, or
    max_interval_yr, whichever is smaller.
  * Round the interval DOWN to a whole number of years. An inspection interval
    is never rounded up. Example: a remaining life of 7.9 years gives 3.95,
    which becomes 3 years.
  * If the interval works out as less than 1 year, use 1 year.
  * If remaining_life_yr is 0 or less, the equipment is already due: return the
    last inspection date unchanged.
  * Add whole years to the date. If the day does not exist in the target year --
    29 February plus one year -- use the last day of that month instead.
  * If last_inspection is not a valid "DD-MM-YYYY" date, raise ValueError.
    If max_interval_yr is less than 1, raise ValueError.

You may use the `datetime` and `calendar` modules. Do not print anything and do
not read any files. Only define the function."""

DUE_ACCEPTANCE = '''
"""Acceptance tests for next_due_date(). The model does not see this file."""
import sys

try:
    from solution import next_due_date
except Exception as e:
    print(f"could not import next_due_date from solution.py: {type(e).__name__}: {e}")
    sys.exit(1)

failures = []

def check(name, got, want):
    if got != want:
        failures.append(f"{name}\\n     got:  {got}\\n     want: {want}")

# 1. the ordinary half-life case: 12.4 years left -> 6.2 -> 6 years
check("half the remaining life, rounded down",
      next_due_date("03-02-2026", 12.4, 10), "03-02-2032")

# 2. the maximum interval caps it
check("the maximum interval caps the half-life",
      next_due_date("03-02-2026", 40.0, 10), "03-02-2036")

# 3. rounded DOWN, never to nearest: 7.9 / 2 = 3.95 -> 3, not 4
check("an interval is rounded down, not to nearest",
      next_due_date("15-06-2025", 7.9, 10), "15-06-2028")

# 4. a short remaining life still gives at least one year
check("less than a year becomes one year",
      next_due_date("15-06-2025", 1.5, 10), "15-06-2026")

# 5. no remaining life -> already due
check("no remaining life means already due",
      next_due_date("15-06-2025", 0.0, 10), "15-06-2025")
check("negative remaining life means already due",
      next_due_date("15-06-2025", -3.0, 10), "15-06-2025")

# 6. 29 February plus three years lands on a day that does not exist
check("29 February is clamped to the end of the month",
      next_due_date("29-02-2024", 6.0, 10), "28-02-2027")
# ... and plus four years it exists again
check("29 February four years on is still 29 February",
      next_due_date("29-02-2024", 8.0, 10), "29-02-2028")

# 7. bad input is refused, not guessed
for bad in ("2026-02-03", "31-02-2026", "not a date", ""):
    try:
        next_due_date(bad, 10.0, 10)
        failures.append(f"last_inspection={bad!r} should raise ValueError, but returned a value")
    except ValueError:
        pass
    except Exception as e:
        failures.append(f"last_inspection={bad!r} should raise ValueError, raised {type(e).__name__}")
try:
    next_due_date("03-02-2026", 10.0, 0)
    failures.append("max_interval_yr=0 should raise ValueError, but returned a value")
except ValueError:
    pass
except Exception as e:
    failures.append(f"max_interval_yr=0 should raise ValueError, raised {type(e).__name__}")

if failures:
    print(f"{len(failures)} acceptance test(s) failed:\\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all acceptance tests passed")
'''

TASKS = {
    "cml_report": CodingTask(
        task_id="cml_report",
        brief=CML_BRIEF,
        entry="solution.py",
        acceptance=CML_ACCEPTANCE,
        max_attempts=3,
    ),
    "remaining_life": CodingTask(
        task_id="remaining_life",
        brief=RATE_BRIEF,
        entry="solution.py",
        acceptance=RATE_ACCEPTANCE,
        max_attempts=3,
    ),
    "next_due_date": CodingTask(
        task_id="next_due_date",
        brief=DUE_BRIEF,
        entry="solution.py",
        acceptance=DUE_ACCEPTANCE,
        max_attempts=4,
    ),
}
