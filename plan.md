# Implementation Plan

Build plan for the AI Customer Complaint & Case Processing System, derived from `project_details.docx`. Stack decisions and graded constraints live in `CLAUDE.md`; this document covers what to build, in what order.

## Objective

A batch workflow that reads complaint documents from `data/`, runs three separate LLM tasks against each one, and writes structured data, customer emails, case summaries, and a consolidated report into `output/`.

## Deliverables checklist

Certification is graded on these. Track them to completion.

- [ ] Working source code, modular and readable
- [ ] Support for at least two of `.txt`, `.pdf`, `.docx`
- [ ] Pydantic-validated structured extraction, never raw LLM text
- [ ] Customer response email per complaint
- [ ] Internal case summary per document
- [ ] `output/final_report.csv` consolidating all documents
- [ ] Sample input documents committed under `data/`
- [ ] Sample outputs committed under `output/`
- [ ] `README.md` covering architecture, setup, approach, and how to run
- [ ] Git history showing incremental work

## Repository layout

```
Project1/
├── data/                          sample complaint documents
├── output/
│   ├── structured_data/           one JSON per document
│   ├── customer_emails/           one .txt or .md per document
│   ├── case_summaries/            one .md per document
│   └── final_report.csv
├── complaint_processor/
│   ├── config.py                  env loading, paths, model name
│   ├── logging_setup.py           logging configuration
│   ├── schemas.py                 all Pydantic models
│   ├── ingestion/
│   │   ├── base.py                SourceDocument model, loader protocol
│   │   ├── txt_loader.py
│   │   ├── pdf_loader.py
│   │   ├── docx_loader.py
│   │   └── registry.py            extension to loader mapping
│   ├── chains/
│   │   ├── extraction.py
│   │   ├── email.py
│   │   └── summary.py
│   ├── orchestrator.py            per-document pipeline plus batch fan-out
│   └── reporting.py               writes all four output artifacts
├── tests/
├── main.py                        CLI entry point
├── app.py                         Streamlit entry point
├── requirements.txt
├── .env.example
├── .gitignore
├── CLAUDE.md
├── plan.md
└── README.md
```

## Dependencies

`langchain`, `langchain-openai`, `pydantic`, `python-dotenv`, `pypdf`, `python-docx`, `pandas`, `streamlit`, `pytest`.

## Data model

`schemas.py` holds four models.

**SourceDocument** carries `filename`, `path`, `file_type`, and `text`. Produced by ingestion, consumed by every chain.

**ComplaintExtraction** is the graded schema and must carry all ten required fields: customer name, email, phone number, complaint category, issue description, resolution provided, is complaint, escalation required, supporting document available, overall case status. Use `Optional[str]` for contact fields, since a source document may genuinely omit them, and booleans for the three yes/no flags. Constrain complaint category and case status with `Literal` or an `Enum` so the report has stable values to group by.

**CustomerEmail** carries `subject` and `body`.

**CaseSummary** carries `case_overview`, `key_issue`, `action_taken`, `current_status`, `recommended_next_action`, matching the five fields the spec names.

**ProcessingResult** bundles the document, the three outputs, and an optional error, so a failed document still flows through the batch and appears in the report.

## Pipeline design

Three chains, each built with `ChatOpenAI` and a `PydanticOutputParser` or the structured-output binding. Keep prompts in their own chain module.

1. **Extraction.** Input is raw document text. Output is `ComplaintExtraction`. The prompt must instruct the model to return null rather than guess when a field is absent.
2. **Email.** Input is the validated extraction, not the raw text. Output is `CustomerEmail`. The prompt must forbid inventing facts, ticket numbers, dates, or compensation not present in the input.
3. **Summary.** Input is the validated extraction. Output is `CaseSummary`.

Chains two and three depend only on chain one, so they run concurrently per document. Across documents, fan out with a thread pool sized from config. This gives the parallel execution the spec invites while keeping the dependency structure visible.

The orchestrator owns this control flow. Entry points call it and nothing else.

## Build phases

**Phase 1: Foundation.** Create the layout, `requirements.txt`, `.gitignore` excluding `.env` and `.venv`, `.env.example`, config loading, and logging setup. Initialize git. Verify the package imports.

**Phase 2: Ingestion.** Implement the three loaders behind a shared interface and the extension registry. Unsupported extensions are skipped with a warning, not an exception. Verify by loading a sample of each format and printing character counts.

**Phase 3: Schemas.** Write all Pydantic models. Verify by instantiating each from a hand-written dict.

**Phase 4: Extraction chain.** Build and test against one real document before touching the other chains. This is the highest-risk step, since every downstream task consumes its output.

**Phase 5: Email and summary chains.** Both consume the extraction. Verify tone and that no invented details appear.

**Phase 6: Orchestrator.** Per-document sequencing, concurrency, and per-document error isolation.

**Phase 7: Reporting.** Write the four artifacts. The CSV holds one row per document with the extraction fields plus a processing status column, built with pandas.

**Phase 8: Entry points.** CLI with arguments for input folder, output folder, and worker count. Streamlit app for upload and result inspection. Neither contains prompts or API calls.

**Phase 9: Sample data.** Author five complaint documents spanning all three formats and covering edge cases: a resolved case, an open escalation, one with missing contact details, and one that is an enquiry rather than a complaint. The last two prove the schema and the complaint flag behave.

**Phase 10: Tests and documentation.** Unit tests for loaders, schema validation, and report generation, mocking the LLM. Then write `README.md` and commit sample outputs.

## Error handling

Failures are contained at the document level. A loader error, a parse failure, or an API error marks that document failed, logs the exception with the filename, and lets the batch continue. Wrap each chain call so a validation failure retries once before being recorded as failed. The final report must show failed documents rather than silently omitting them.

Log to both console and `output/run.log` at INFO, with DEBUG available via a CLI flag.

## Verification

End to end: place the five sample documents in `data/`, run `python main.py`, and confirm `output/` contains one JSON, one email, and one summary per document plus a five-row CSV. Then delete a required field from one source document and confirm the run completes with nulls rather than fabricated values. Finally run `streamlit run app.py`, upload a document, and confirm the same three outputs render.
