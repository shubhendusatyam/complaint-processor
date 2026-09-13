# AI Customer Complaint & Case Processing System

A batch workflow that reads customer complaint documents from a folder and, for each one, runs three separate AI tasks: it extracts structured case data, drafts a customer reply, and writes an internal case summary. Results are consolidated into a single CSV report.

Built with Python, LangChain and the OpenAI API, using Pydantic for structured output. It runs entirely on a local machine and needs no infrastructure beyond an API key.

---

## What it produces

For a folder of complaint documents, one run produces:

| Output | Contents |
| --- | --- |
| `output/structured_data/*.json` | The validated extraction for each document |
| `output/customer_emails/*.txt` | A customer-facing reply for each case |
| `output/case_summaries/*.md` | An internal summary for a case manager |
| `output/final_report.csv` | One row per input document, including failures |

Input formats supported: `.txt`, `.pdf` and `.docx`.

---

## Architecture

The system is six layers, each with a single responsibility. Nothing skips a layer.

```
  data/*.txt .pdf .docx
          |
   [ 1. Ingestion ]        one loader per format, behind a shared interface
          |                returns SourceDocument (text + provenance)
          v
   [ 2. Schemas ]          Pydantic models define every AI task's output
          |
          v
   [ 3. Chains ]           three LangChain chains, one per AI task
          |
          v
   [ 4. Orchestration ]    sequences the tasks, fans out across documents,
          |                contains failure per document
          v
   [ 5. Reporting ]        writes the four artifacts
          |
          v
   [ 6. Entry points ]     main.py (CLI) and app.py (Streamlit)
```

### The workflow

The three AI tasks are orchestrated, not merged into one prompt. The dependency between them is what makes this a workflow:

```
                   ┌──────────────────────┐
   document text ─▶│  1. Extraction       │
                   │  → ComplaintExtraction│
                   └──────────┬───────────┘
                              │  validated case data
                  ┌───────────┴───────────┐
                  ▼                       ▼          (these two run
       ┌──────────────────┐    ┌────────────────────┐  concurrently)
       │ 2. Customer email│    │ 3. Case summary    │
       │ → CustomerEmail  │    │ → CaseSummary      │
       └──────────────────┘    └────────────────────┘
```

Extraction must finish first, because the other two consume its output rather than the raw document. Once it is available, the email and summary tasks have no dependency on each other and run together through LangChain's `RunnableParallel`.

There are two levels of concurrency: the two follow-up tasks within a document, and a thread pool across documents.

### Why the follow-up tasks read the extraction, not the document

Feeding the email and summary tasks the validated extraction rather than the original text means they can only restate facts that already passed schema validation. A fluent, well-written email that invents a refund amount or a delivery date is the most damaging output this system could produce, and this structure removes the raw material for it.

---

## Project structure

```
Project1/
├── complaint_processor/
│   ├── config.py            settings from .env, path resolution, validation
│   ├── logging_setup.py     console + file logging
│   ├── schemas.py           all Pydantic models
│   ├── ingestion/
│   │   ├── base.py          SourceDocument, loader contract, text normalization
│   │   ├── txt_loader.py    plain text, with encoding fallback
│   │   ├── pdf_loader.py    PDF via pypdf
│   │   ├── docx_loader.py   Word, including table cells
│   │   └── registry.py      extension → loader; the only format-aware module
│   ├── chains/
│   │   ├── base.py          model factory, retry policy, prompt input helpers
│   │   ├── extraction.py    task 1
│   │   ├── email.py         task 2
│   │   └── summary.py       task 3
│   ├── orchestrator.py      per-document pipeline and batch fan-out
│   └── reporting.py         writes the four output artifacts
├── tests/                   74 tests; the LLM is stubbed, so they cost nothing
├── data/                    five sample complaint documents
├── output/                  a committed sample run of those documents
├── main.py                  command line entry point
├── app.py                   Streamlit entry point
├── server.py                HTTP entry point (FastAPI, deployed to Vercel)
├── vercel.json              serverless function config
└── requirements.txt
```

---

## Setup

Requires Python 3.10 or newer. Developed on 3.13.

**1. Create and activate a virtual environment**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

On macOS or Linux, use `source .venv/bin/activate`.

**2. Install dependencies**

```powershell
pip install -r requirements.txt
```

**3. Add your API key**

```powershell
Copy-Item .env.example .env
```

Then open `.env` and replace the placeholder:

```
OPENAI_API_KEY=sk-your-real-key-here
```

`.env` is git-ignored and never committed. Get a key at <https://platform.openai.com/api-keys>. The account needs credits; a key with a zero balance authenticates successfully but every request fails.

### Configuration

All optional, set in `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | Required |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model used by all three tasks |
| `OPENAI_TEMPERATURE` | `0.0` | Base temperature; the email task adds a little warmth |
| `MAX_WORKERS` | `4` | Documents processed concurrently |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

---

## Running it

### Command line

```powershell
python main.py
```

Processes everything in `data/` and writes to `output/`. Options:

```powershell
python main.py --data-dir samples --output-dir results
python main.py --workers 8
python main.py --log-level DEBUG
```

Exit codes are distinct so a scripted run can tell outcomes apart:

| Code | Meaning |
| --- | --- |
| `0` | Every document processed successfully |
| `1` | At least one document failed, or no documents were found |
| `2` | Configuration problem, such as a missing key or input folder |

### Browser interface

```powershell
streamlit run app.py
```

Opens at <http://localhost:8501>. Either upload documents directly or process the `data/` folder, then inspect each case across three tabs: extracted data, the generated email, and the case summary.

### HTTP API

A third interface onto the same workflow, for deployment. It processes **one
document per request** and returns JSON.

```powershell
pip install uvicorn                       # the rest comes from requirements.txt
python -m uvicorn server:app --reload
```

Opens at <http://localhost:8000>, which serves a minimal upload form.

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Readiness and whether the API key is configured |
| `GET /api/samples` | Names of the documents in `data/` |
| `POST /api/process` | Process one uploaded file (multipart `file` field) |
| `POST /api/process/sample/{name}` | Process one committed sample |
| `GET /api/diagnostics` | What the function can see on disk; for deployment problems |

```powershell
curl.exe -F "file=@data/complaint_001.txt" http://localhost:8000/api/process
```

A document that fails returns HTTP 200 with `"status": "failed"` and a reason,
matching how a failure is recorded in the batch report rather than aborting it.

### Tests

```powershell
pytest                                                # full suite
pytest tests\test_ingestion.py                        # one file
pytest tests\test_schemas.py::TestNullNormalization   # one class
```

The model is stubbed throughout, so the suite runs offline and costs nothing.

### Regenerating the sample documents

```powershell
python -m tests.make_sample_data
```

---

## Approach and design decisions

**Structured output rather than parsed text.** Every AI task is bound to a Pydantic model through `with_structured_output(..., strict=True)`. No raw model response is ever saved. Validators reject values that would be misleading in a report: placeholders such as `N/A` become null, and anything in the email field that is not an address is discarded, on the grounds that a blank column is safer than a fabricated one.

**Prompts that permit "I don't know".** The extraction prompt states that a missing field is a correct answer, that a name must never be inferred from an email address, and that a promised action is not a completed one. In testing, a document describing an engineer visit that was promised but never happened correctly recorded no resolution.

**Failure is contained at the document level.** A document that cannot be read, or whose extraction fails, becomes a result object carrying the reason rather than an exception. One unreadable file never ends a batch, and every input file appears in the final report, so nothing disappears silently.

**Three result states, not two.** `success` means all three outputs exist, `failed` means extraction never succeeded, and `partial` means the structured data is sound but a follow-up task failed. The distinction matters operationally: a partial case needs one task re-run, not the whole document.

**Word documents are read including tables.** Complaint forms routinely put the customer name, email and phone in a table. A paragraph-only reader returns a document that looks fine but has lost exactly the fields the extraction needs.

**Everything is written as UTF-8.** Generated emails contain curly quotes and accented names. The CSV additionally carries a byte order mark so that Excel displays them correctly.

---

## Sample data

The five documents in `data/` are deliberately varied rather than near-duplicates, so a run exercises different paths:

| File | What it tests |
| --- | --- |
| `complaint_001.txt` | A complete, resolved case with supporting evidence |
| `complaint_002.pdf` | An open escalation with a legal threat and a broken promise |
| `complaint_003.txt` | An enquiry, not a complaint, so the complaint flag must be false |
| `complaint_004.pdf` | No name and no phone, so the model must not invent them |
| `complaint_005.docx` | Customer details inside a Word table |

`output/` holds a real run of these five.

---

## Troubleshooting

**`OPENAI_API_KEY is still the placeholder value`** — `.env` was copied but not edited. Replace the placeholder with your real key.

**`429 insufficient_quota`** — the key is valid but the account has no credits.

**`contains no extractable text`** — the PDF is a scanned image. Text extraction cannot read it; that would need optical character recognition, which is out of scope here.

**A document is reported as `failed`** — the reason is in the report's `error` column and in `output/run.log`. The rest of the batch is unaffected.

---

## Deployment

The Streamlit app cannot be hosted on a serverless platform: it is a long-lived
process holding a WebSocket per browser. `server.py` exists so the workflow
can still be reached over HTTP, as a stateless request/response function.

Three constraints shape it, all imposed by the runtime:

- **One document per request.** A whole batch of LLM calls does not fit inside
  the function timeout, and there is no durable disk to write a report to.
- **`/tmp` is the only writable path.** Uploads are staged there and the log
  file is redirected there; the repository filesystem is read-only at runtime.
- **Dependencies are read only from the project root.** `fastapi` and
  `python-multipart` therefore live in `requirements.txt`, not beside the
  entrypoint. A `requirements.txt` placed anywhere else is ignored, and the
  function then crashes on `ModuleNotFoundError: No module named 'fastapi'`.

There is no tree-shaking: every project file reachable at build time is bundled,
so `complaint_processor/` and `data/` ship without being named anywhere.
`excludeFiles` in `vercel.json` keeps tests, `output/` and the spec out, well
inside the 500 MB bundle limit.

Deploying to Vercel:

1. Import the repository at <https://vercel.com/new>.
2. Add `OPENAI_API_KEY` under **Settings → Environment Variables**. The key is
   supplied by the platform, never committed — `.env` is for local runs only.
3. Deploy. `vercel.json` allows 60 seconds per request and trims the bundle.

The entrypoint is resolved by filename, which is why the HTTP layer is
`server.py` at the project root rather than something more descriptive deeper
in the tree. Vercel scans the root for `app.py`, `index.py`, `server.py`,
`main.py`, `wsgi.py`, `asgi.py` and takes the first that exports an ASGI `app`.
Two of those names are already taken here by things that are not ASGI apps, so
`.vercelignore` excludes `app.py` and `main.py` from the deployment — that
exclusion is load bearing, not tidying. Once resolved, Vercel routes every
request to the app, so no rewrite rules are needed.

Pinning the entrypoint through `tool.vercel.entrypoint` in a `pyproject.toml`
is the documented alternative, but it is not usable here: the moment that file
exists the runtime installs dependencies from it with `uv` instead of reading
`requirements.txt`, which would mean maintaining the dependency list twice.

New deployments have **Deployment Protection** enabled by default, which answers
every request with a redirect to a Vercel login page. That is a project setting,
not a code problem: a browser signed in to the Vercel account gets through while
`curl` and any other client get a 302. Turn it off under **Settings → Deployment
Protection** if the API is meant to be callable.

If a deployment does misbehave, `GET /api/diagnostics` reports whether the
package was bundled, the Python version, and whether the key is set, without
disclosing any values. A packaging failure is otherwise invisible: the module
fails to import and the platform reports only that the invocation failed.

The CLI and the Streamlit app remain the primary interfaces, and both run
locally as the specification intends.

---

## Technologies

Python · LangChain · OpenAI API · Pydantic · pandas · Streamlit · pypdf · python-docx · pytest
