# Vendor Onboarding: AI-assisted, human-in-the-loop

A working vendor onboarding process. A vendor submits a form and PDFs; the system checks
them with transparent rules and AI document reading, recommends **Approved / Pending /
Rejected** with reasons and next actions, and a human reviewer makes the final decision.
Reviewer corrections feed back into future AI extraction and review prioritisation.

All test data is synthetic. The app never claims a document is genuine or that a bank
account belongs to the vendor; it reports what it read and checked.

## How it works

Submit form + PDFs → rule checks → AI reads each PDF (scans are read from page images) →
form vs document comparison → recommendation with reasons → prioritised review queue →
human decision (approve / request info / reject / escalate) → audit log + feedback store

## Screens
- **Dashboard:** pipeline counts, reviewer workload, AI–human disagreement, corrections
  captured, test-set accuracy, all vendors, why cases are pending, recent activity
- **Submit Vendor:** form, PDF uploads and a live run view showing each stage as it runs
- **Review Queue:** cases ordered by transparent priority tiers
- **Vendor Detail:** summary, form vs documents, every check with evidence, extracted
  fields with quotes, reviewer actions, full history
- **Learning and Metrics:** what adapts from reviewer feedback, check reliability,
  corrections, test-set results

## Run locally
    py -m venv .venv
    .venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    python sample_data/make_samples.py
    streamlit run dashboard.py

For AI extraction, create `.streamlit/secrets.toml`:

    AI_PROVIDER = "gemini"
    GEMINI_API_KEY = "your-key"
    AI_MODEL = "gemini-3.5-flash-lite"

OpenAI is also supported (`AI_PROVIDER = "openai"`, `OPENAI_API_KEY`). Without a key the
app still runs, using a clearly labelled pattern-matching fallback (not AI).

## Key design decisions
- **No scores, no averaging.** One open critical issue keeps a case Pending, however many
  other checks pass.
- **Missing or uncertain information never causes rejection.** The only automatic
  rejection rule is a match on a (synthetic) blocked-party list, and a human confirms it.
- **Evidence for every AI value:** an exact quote, checked against the PDF text. Values
  whose quotes are not found are downgraded to low confidence.
- **Scanned documents** are read by the AI from page images, capped at medium confidence,
  and always sent to a human to confirm.
- **Review queue** is ordered by transparent tiers (critical issues first), not by AI
  confidence: a confident extraction can still reveal a serious mismatch.
- **Clear next steps:** every non-approved case says what the vendor must send and what
  the reviewer must check.

## Feedback loop: what adapts and when
| Component | How it changes | When |
|---|---|---|
| AI extraction | Recent reviewer corrections are added to the prompt as examples | Immediately |
| Review queue order | Per-check false-alarm rates reorder cases within a tier | Immediately |
| Validation and decision rules | Never automatically; changed by a person and re-tested | Manual |
| The AI model itself | Not retrained in this MVP | Future, after evaluation |

## Results on the labelled synthetic test set
6 vendors, 16 documents (one scanned): field accuracy 59/59, recommendation accuracy 6/6,
using Gemini 3.5 Flash-Lite. These are clean synthetic documents, so this shows the
pipeline works end to end; it is not evidence of real-world accuracy.
Run: `python evaluation/evaluate.py`

## Edge cases handled
Bank account holder differs from the vendor · tax ID on the certificate differs from the
form · scanned document with no text layer · missing fields and documents · country
without configured rules (flagged for a specialist) · invalid IBAN or routing checksum ·
non-PDF or password-protected upload · AI service error (falls back and says so)

## Not verified (by design)
Document authenticity, bank account ownership, company registry existence, tax ID
validity with tax authorities, real sanctions screening.

## Deployment note
On Streamlit Community Cloud the SQLite database and uploaded files reset when the app
restarts or sleeps. Production would use a hosted database and object storage; only
`core/database.py` and `core/storage.py` would need to change.