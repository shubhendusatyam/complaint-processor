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

- **Ingestion.** One loader per file format behind a shared interface, returning extracted text plus source metadata. Format detection happens here and nowhere else.
- **Schemas.** The Pydantic models, including the extraction model above and the models for the email and summary outputs.
- **Chains.** Three LangChain chains, one per AI task. Each owns its own prompt template and output parser.
- **Orchestration.** Runs the three chains for a single document, and fans out across the document set.
- **Reporting.** Writes the four output artifacts under `output/`: structured data, customer emails, case summaries, and the consolidated `final_report.csv`.
- **Entry points.** A CLI and a Streamlit app, both thin.

The rule that keeps this clean: entry points and the Streamlit app hold no prompt text and make no API calls. Both delegate to the orchestration layer. If a prompt string appears in the Streamlit file, the layering has broken down.

## Commands

Setup is done; `.venv` exists with dependencies installed. Entry points arrive in Phase 8.

```powershell
.\.venv\Scripts\Activate.ps1      # then plain `python` and `pytest` work
pip install -r requirements.txt   # after changing dependencies

python main.py                    # batch run over data/ (Phase 8)
streamlit run app.py              # browser UI (Phase 8)

pytest                            # full suite
pytest tests\test_extraction.py::test_missing_phone_number   # single test
```

Without activating, call the interpreter directly as `.\.venv\Scripts\python.exe`.

## Environment notes

The shell is Windows PowerShell 5.1, which has no `&&` chaining. Sequential commands use `;` with an `if ($?)` guard when the second step depends on the first. The repository path contains a space, so quote paths.

Git 2.55 is installed at `C:\Program Files\Git\cmd`, which is on the user PATH. If bare `git` reports "not recognized", the session's environment predates the install and needs a restart; until then invoke it by full path as `& "C:\Program Files\Git\cmd\git.exe"`. Repository-local `user.name` and `user.email` are set; change them with `git config user.name "..."` if the attribution is wrong.
