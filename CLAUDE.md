# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

This is the final evaluation project for a GenAI Development Program. The authoritative specification is `project_details.docx` in the repository root; read it before making design decisions, as certification is graded against it.

The application is an AI Customer Complaint & Case Processing System: a batch workflow that reads complaint documents from `data/`, and for each one produces a structured extraction, a customer response email, and an internal case summary, then consolidates everything into a report.

**The repository is currently empty apart from the spec.** Everything below describes the agreed target design, not existing code. Replace these sections with descriptions of the real implementation as it lands.

## Graded constraints

These come directly from the spec and are the easiest things to violate without noticing.

- Implementation must be primarily Python, run locally, and avoid expensive or complex external infrastructure.
- Structured extraction must pass through a Pydantic schema. The spec explicitly forbids saving the raw LLM response as the output.
- The three AI tasks must be separately orchestrated steps. One large prompt that does all three fails the stated intent, which is to demonstrate workflow orchestration.
- Generated emails and summaries must not introduce facts absent from the source document.
- At least two of `.txt`, `.pdf`, and `.docx` must be supported as input formats.
- A single document failure is logged and skipped. It must never abort the batch.
- `README.md` covering architecture, setup, approach, and run instructions is part of the deliverable, not optional polish.
- Sample input documents and sample outputs are submitted alongside the source code.

The extraction schema must carry these ten fields: customer name, email, phone number, complaint category, issue description, resolution provided, complaint yes/no, escalation required yes/no, supporting document available yes/no, and overall case status.

## Stack

Confirmed choices for this project:

| Concern | Choice |
| --- | --- |
| LLM provider | OpenAI |
| Orchestration | LangChain |
| Structured output | Pydantic |
| Interfaces | CLI and Streamlit |
| Tests | pytest |
| Config | python-dotenv |

`OPENAI_API_KEY` is read from a `.env` file that stays out of version control. Copy `.env.example` to `.env` to get started.

**LangChain 1.x is installed and required.** `requirements.txt` pins `>=1.0,<2`. The legacy `LLMChain` and `PydanticOutputParser` pattern from the 0.x line does not apply. Build the three chains with `ChatOpenAI(...).with_structured_output(Model)` composed via LCEL.

## Target architecture

Six layers, each with one responsibility.

- **Ingestion.** Built. One loader per format behind a shared `extract_text(path) -> str` interface, with `registry.py` as the only module that knows which formats are supported. Adding a format means writing a loader and adding one entry to `LOADERS`. Loaders raise `DocumentLoadError`; the caller decides whether to skip. Note that the Word loader reads table cells as well as paragraphs, because complaint forms put customer details in tables.
- **Schemas.** Built, in `schemas.py`. Holds `ComplaintExtraction` (the ten graded fields), `CustomerEmail`, `CaseSummary`, and `ProcessingResult`, which bundles one document's outputs and carries failures into the report instead of dropping them. Category and status are enums, so the report can be grouped reliably. Validators map placeholder values such as "N/A" to null and discard anything in the email field that is not an address. **The field descriptions are sent to the model as part of the JSON schema and are the main lever on extraction quality; treat them as prompt text, not comments.**
- **Chains.** All three are built. `base.py` holds the model factory, the retry policy and an input length guard, so the model is changed in one place. `extraction.py` binds its prompt to `ComplaintExtraction` with `strict=True`, verified working against the live API. Chain builders accept `retry=False` so tests skip the backoff. Failures raise `ChainError` naming the file, which is what lets the batch continue.
- **Orchestration.** Built, in `orchestrator.py`. `Workflow.build()` constructs the three chains once and shares them across every document. Within a document, extraction runs first because the other two consume it, then email and summary run together via `RunnableParallel`. Across documents a thread pool fans out, and results are re-sorted into input order so the report is reproducible. `process_document` and `process_file` never raise: every failure becomes a `ProcessingResult` carrying the reason.
- **Reporting.** Built, in `reporting.py`. `write_all(results)` produces all four artifacts and returns counts. JSON extractions are wrapped with their source filename and status; emails and summaries are skipped rather than written empty when a task failed. The CSV uses `utf-8-sig` so Excel reads accented names correctly, and carries a row for every input file including failures. `output_stem` folds the extension into the name when two sources share a stem, so `complaint_001.txt` and `complaint_001.pdf` cannot overwrite each other.
- **Entry points.** Built. `main.py` parses arguments, delegates, and prints a summary; it exits 0 on a clean batch, 1 when any document failed or none were found, and 2 on a configuration problem. `app.py` runs the same orchestrator, caching the workflow with `st.cache_resource` and staging uploads to a temp folder so the loaders read them by path exactly as the CLI does. `server.py` is a third interface, a FastAPI app deployed to Vercel; it is one-document-per-request because a batch does not fit a function timeout, and writes only to `/tmp` because the deployed filesystem is read-only. **Its dependencies belong in the root `requirements.txt`** — the runtime reads only the project root, so a `requirements.txt` beside the entrypoint is silently ignored and the function dies on `ModuleNotFoundError`. Do not add a `pyproject.toml`: its presence switches dependency installation to `uv` reading that file alone, and it must then carry a `[project]` table or the build fails outright. The entrypoint is resolved by filename from a fixed list, which is why the file is `server.py` at the root and why `.vercelignore` must keep excluding `app.py` and `main.py`. Nothing needs listing to be bundled: every reachable project file ships, and `excludeFiles` trims what should not.

A `ProcessingResult` has three states, not two. `failed` means no extraction, `partial` means the structured data is sound but a follow-up task is missing, and `success` means all three outputs exist. `partial` is worth keeping distinct: it needs one task re-run, not the whole document.

**Write every output file with `encoding="utf-8"`.** Generated emails contain curly quotes and other non-ASCII characters, and the Windows default codepage mangles or rejects them.

The rule that keeps this clean: entry points and the Streamlit app hold no prompt text and make no API calls. Both delegate to the orchestration layer. If a prompt string appears in the Streamlit file, the layering has broken down.

## Commands

Setup is done; `.venv` exists with dependencies installed.

```powershell
.\.venv\Scripts\Activate.ps1      # then plain `python` and `pytest` work
pip install -r requirements.txt   # after changing dependencies

python main.py                    # batch run over data/
python main.py --workers 8 --log-level DEBUG
streamlit run app.py              # browser UI
python -m tests.make_sample_data  # regenerate data/ samples

pytest                            # full suite
pytest tests\test_schemas.py::TestNullNormalization          # single class
```

Without activating, call the interpreter directly as `.\.venv\Scripts\python.exe`.

## Environment notes

The shell is Windows PowerShell 5.1, which has no `&&` chaining. Sequential commands use `;` with an `if ($?)` guard when the second step depends on the first. The repository path contains a space, so quote paths.

Git 2.55 is installed at `C:\Program Files\Git\cmd`, which is on the user PATH. If bare `git` reports "not recognized", the session's environment predates the install and needs a restart; until then invoke it by full path as `& "C:\Program Files\Git\cmd\git.exe"`. Repository-local `user.name` and `user.email` are set; change them with `git config user.name "..."` if the attribution is wrong.
