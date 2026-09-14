# Demo run sheet — R-2247 mission and chat

For whoever presents and whoever drives the keyboard. Every step below is a real
run on this machine: nothing is animated. Timings marked *(rehearsal)* come from
the browser rehearsal on 14 Sep 2026 and will vary a little.

---

## Before judges arrive (15 minutes)

| # | Do | Check |
|---|---|---|
| 1 | Docker Desktop running | `docker info` answers |
| 2 | Start Ollama offline: `$env:OLLAMA_NO_CLOUD = "1"; ollama serve` | `ollama list` shows `granite4.1:8b` |
| 3 | Start the service: `$env:LANGSMITH_TRACING = "false"; .venv\Scripts\python -m workbench.server` | it prints `http://127.0.0.1:8770` |
| 4 | Open http://127.0.0.1:8770 | the start screen says **Ready**; footer shows **external connections 0** |
| 5 | Warm-up: press **Run demo** once, let it finish, then press **New chat** | loads the models, so the real run is quick |

Do **not** restart the service between the warm-up and the demo if you want to
use a run that is already paused. A restart forgets paused runs; running the
demo again makes a new one.

---

## The mission (about 3 minutes with talking)

*(rehearsal, 5 runs)* Run demo 24–50 s from press to "Mission finished"; the 12.3
refusal about 1 s; the resumed run 7 s. The Coder passed on attempt 1 in the last
three runs, but in the first it did **not** pass in 4 attempts and handed the job to
a person — expect that sometimes, and use the line under *If something goes wrong*.

| Step | Driver does | Judges see | Presenter says |
|---|---|---|---|
| 1 | Press **Run demo** | The request appears in chat. In **Agent Activity** the **Planner** plans it: 3 steps, checked in code, plus 1 step marked *from the demo scenario* | "One request in plain words. The Planner splits it into steps our agents can do, and code checks the plan before anything runs. It can't pick a report you didn't name." |
| 2 | Nothing | **Document Reader → Evidence Builder → Rules Engine → Report Writer → QA Checker**. A wrong number is injected on purpose; the QA Checker catches it and sends the note back; attempt 2 passes. **ESCALATE: CML-03 12.32 < 12.70** | "The rules decide in code, not the model. We broke the note on purpose, and the checker read the Word file back and caught it." |
| 3 | Nothing | **Librarian**: SOP-INSP-001 §4 "Escalation triggers", p. 1, and the other passages in **Evidence** | "Every passage is cited. If it isn't in the library, it says so." |
| 4 | Nothing | The same report with a **blurred digit**: the run **pauses for a person**. The **Review** tab gets a badge | "The column prints two decimals and this cell reads one. It stops instead of guessing." |
| 5 | Nothing | **Coder → Sandbox**: writes a program for the next due date and runs it sealed, against tests it never sees | "No network, no host files. If a test fails it reads the failure and fixes it. If it runs out of attempts it hands the job to a person, and says so." |
| 6 | Open **Review**. Type `12.3`, a name, press **Confirm values and resume** | Refused: the column prints 2 decimals | "Code checks what a person types, too." |
| 7 | Change it to `12.32`, press **Confirm values and resume** | A **Resumed** group: ESCALATE, and a checked note whose appendix records who entered the value and what the scan read | "It resumes from exactly that step, and the note records who entered what." |
| 8 | Open **Why this model** | Each task with the model chosen and the measured result behind it | "Every model earned its job on our tests. A model that ever wrote a false approval is shut out." |
| 9 | Point at the footer | **external connections 0**, audit logs intact | "Nothing left the machine, and the logs are hash-chained." |

Name to type at step 6: **[team to choose]**.

---

## Chat (optional, about 1 minute of waiting)

*(rehearsal)* greeting 11 s, E-4461 note 14 s, V-1668 note + email 13 s, plates 6 s.

Press **New chat** first. Type each line and press Enter.

| Type | Expect |
|---|---|
| `Hello! What can you do?` | A short friendly answer, labelled *general answer, not from your documents* |
| `Draft the approval note for exchanger E-4461.` | Planner: 1 step; the inspection runs; a draft note |
| `Draft the approval note for V-1668 and email it to the vendor.` | Planner: 1 step for the note, and "not in the plan: emailing" with why |

Don't type follow-ups like "now do the same for V-1668": chat memory is switched off
until it passes its test, so the Planner will ask which report.
| `Order replacement plates for the tank from the vendor.` | "Nothing was planned", with why, and a list of what the workbench can do |

---

## If something goes wrong

| You see | Say / do |
|---|---|
| Coder "not accepted — handed to a person" | "This is the honest outcome: it didn't pass our tests, so it isn't used." Carry on. |
| Review says "no run is waiting" | The service was restarted. Press **Run demo** again. |
| Start screen "Not ready: Ollama" | Start Ollama (step 2), reload the page |
| "The Planner's plan did not pass its checks" | "It refused its own plan rather than run a wrong one." Retype the request more plainly. |
