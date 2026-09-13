"""HTTP entry point: one complaint document in, the three AI outputs back.

This is a third interface onto the same workflow, alongside main.py and app.py,
and it obeys the same rule they do: it holds no prompt text and makes no API
calls of its own. Parse the request, delegate to the orchestrator, serialize the
ProcessingResult. If a prompt string ever appears here, the layering has broken.

Deployment shape differs from the local ones in three ways, all forced by the
serverless runtime:

  * One document per request, not a batch. A batch of LLM calls does not fit in
    the function timeout, and there is nowhere durable to write the report to.
  * Uploads are staged under /tmp, the only writable path. The loaders read by
    path, exactly as they do for the CLI.
  * Results come back as JSON. The reporting layer is never imported, which
    also keeps pandas and streamlit out of the deployment bundle.

Vercel serves the module-level `app` below as an ASGI application.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from threading import Lock

# api/ sits one level below the package, and the runtime does not put the
# repository root on the path for us.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

# The package is bundled by the includeFiles glob in vercel.json, not by the
# runtime's own dependency detection. If that glob is ever wrong the import
# below is what breaks, and a bare failure here would take the whole module
# down as an opaque FUNCTION_INVOCATION_FAILED with the cause only in the
# platform logs. Capturing it instead lets the deployment report its own
# problem over HTTP.
IMPORT_ERROR: str | None = None
_IMPORT_TRACEBACK: str | None = None

try:
    from complaint_processor.config import ConfigError, settings, validate
    from complaint_processor.ingestion.registry import (
        SUPPORTED_EXTENSIONS,
        discover_documents,
    )
    from complaint_processor.logging_setup import configure_logging, get_logger
    from complaint_processor.orchestrator import Workflow, process_file
    from complaint_processor.schemas import ProcessingResult
except Exception as exc:  # pragma: no cover - deployment packaging failure
    import traceback

    IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
    _IMPORT_TRACEBACK = traceback.format_exc()
    SUPPORTED_EXTENSIONS = frozenset()

# Refuse oversized uploads before reading them into memory. Complaint documents
# are a few kilobytes; anything near this is not one.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

TMP_DIR = Path(tempfile.gettempdir())

# The repository filesystem is read-only at runtime, so the file handler cannot
# go to output/run.log the way it does locally.
if IMPORT_ERROR is None:
    configure_logging(log_path=TMP_DIR / "run.log")
    logger = get_logger(__name__)
else:
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.error("Package import failed, serving diagnostics only: %s", IMPORT_ERROR)

app = FastAPI(
    title="Complaint Processing API",
    description="Structured extraction, customer email and case summary for one "
    "complaint document.",
    version="1.0.0",
)

_workflow: Workflow | None = None
_workflow_lock = Lock()


def get_workflow() -> Workflow:
    """Build the three chains once per warm instance.

    The serverless equivalent of the Streamlit app's st.cache_resource: rebuilding
    the model client on every request would pay the setup cost for nothing.
    """
    global _workflow
    with _workflow_lock:
        if _workflow is None:
            _workflow = Workflow.build()
        return _workflow


def require_package() -> None:
    """Turn a packaging failure into a readable 503 instead of a bare crash."""
    if IMPORT_ERROR is not None:
        raise HTTPException(
            status_code=503,
            detail=(
                f"The complaint_processor package did not import: {IMPORT_ERROR}. "
                "See GET /api/diagnostics for the traceback and what was bundled."
            ),
        )


def require_config() -> None:
    """Fail with a clear 503 rather than a 500 from deep inside a chain.

    data/ is not required: an upload carries its own document, and only the
    sample routes touch the batch folder.
    """
    try:
        validate(settings, require_data_dir=False)
    except ConfigError as exc:
        logger.error("Configuration rejected: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "Service is not configured. Set OPENAI_API_KEY in the Vercel "
                "project's environment variables and redeploy."
            ),
        ) from exc


def serialize(result: ProcessingResult) -> dict:
    """Flatten a ProcessingResult into the JSON response body.

    Mirrors what the reporting layer writes to disk locally: the validated
    extraction, the rendered email and summary, and the status that says which
    of the three tasks actually produced output.
    """
    return {
        "filename": result.filename,
        "file_type": result.file_type,
        "status": result.status,
        "error": result.error,
        "extraction": result.extraction.model_dump(mode="json") if result.extraction else None,
        "customer_email": (
            {
                "subject": result.customer_email.subject,
                "body": result.customer_email.body,
                "rendered": result.customer_email.render(),
            }
            if result.customer_email
            else None
        ),
        "case_summary": (
            result.case_summary.model_dump(mode="json") | {"rendered": result.case_summary.render()}
            if result.case_summary
            else None
        ),
    }


def run_on_path(path: Path) -> dict:
    """Shared tail of both processing routes."""
    require_package()
    require_config()
    result = process_file(path, get_workflow())
    logger.info("Processed %s: %s", result.filename, result.status)
    # A document failure is a valid outcome carrying a reason, not a server
    # error, so it comes back as 200 with status "failed" the same way it lands
    # in the report locally.
    return serialize(result)


@app.get("/api/health")
def health() -> dict:
    """Readiness without spending an API call."""
    if IMPORT_ERROR is not None:
        return {
            "status": "error",
            "configured": False,
            "detail": f"Package import failed: {IMPORT_ERROR}",
            "model": None,
            "supported_formats": [],
        }
    try:
        validate(settings, require_data_dir=False)
        configured = True
        detail = None
    except ConfigError as exc:
        configured = False
        detail = str(exc).splitlines()[0]
    return {
        "status": "ok",
        "configured": configured,
        "detail": detail,
        "model": settings.openai_model,
        "supported_formats": sorted(SUPPORTED_EXTENSIONS),
    }


@app.get("/api/diagnostics")
def diagnostics() -> dict:
    """What the function can actually see on disk.

    Exists because a serverless packaging problem is invisible from the outside:
    the module fails to import and the platform reports only that the invocation
    failed. This answers the question that failure raises, which is whether the
    package was bundled at all. It reveals no secrets: environment variables are
    reported as present or absent, never by value.
    """
    root = Path(__file__).resolve().parent.parent
    try:
        listing = sorted(entry.name for entry in root.iterdir())
    except Exception as exc:
        listing = [f"<unreadable: {exc}>"]

    return {
        "import_error": IMPORT_ERROR,
        "traceback": _IMPORT_TRACEBACK if IMPORT_ERROR else None,
        "python_version": sys.version,
        "function_root": str(root),
        "root_contents": listing,
        "complaint_processor_present": (root / "complaint_processor").is_dir(),
        "data_dir_present": (root / "data").is_dir(),
        "openai_api_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "sys_path": sys.path[:8],
    }


@app.get("/api/samples")
def samples() -> dict:
    """The sample documents committed under data/, processable by name."""
    if IMPORT_ERROR is not None:
        return {"samples": []}
    try:
        found = discover_documents(settings.data_dir)
    except Exception as exc:
        logger.warning("Could not list samples: %s", exc)
        return {"samples": []}
    return {"samples": [path.name for path in found]}


@app.post("/api/process/sample/{name}")
def process_sample(name: str) -> dict:
    """Run the workflow over one committed sample, so the API can be demonstrated
    without an upload."""
    require_package()
    # Resolve and confine to data/ so the name cannot walk out of the folder.
    candidate = (settings.data_dir / name).resolve()
    if not candidate.is_file() or settings.data_dir.resolve() not in candidate.parents:
        raise HTTPException(status_code=404, detail=f"No sample named {name!r}")
    return run_on_path(candidate)


@app.post("/api/process")
async def process_upload(file: UploadFile = File(...)) -> dict:
    """Process one uploaded complaint document."""
    require_package()
    filename = Path(file.filename or "").name
    if not filename:
        raise HTTPException(status_code=400, detail="No file name supplied")

    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported format {suffix or '(none)'}. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail=f"{filename} is empty")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{filename} exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )

    # The loaders read by path, so the upload is staged before processing. A
    # per-request directory keeps concurrent invocations from colliding.
    staging = Path(tempfile.mkdtemp(dir=TMP_DIR))
    staged = staging / filename
    staged.write_bytes(payload)
    try:
        return run_on_path(staged)
    finally:
        staged.unlink(missing_ok=True)
        staging.rmdir()


# A minimal upload form, so the deployment is demonstrable in a browser without
# an HTTP client. The real interface is the JSON API above; the rich UI is the
# Streamlit app, which runs locally.
INDEX_HTML = """<!doctype html>
<title>Complaint Processing API</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 15px/1.55 system-ui, sans-serif; max-width: 46rem; margin: 0 auto;
         padding: 2rem 1rem; }
  code, pre { font-family: ui-monospace, monospace; font-size: .9em; }
  pre { background: rgba(128,128,128,.12); padding: .85rem; border-radius: 6px;
        overflow-x: auto; white-space: pre-wrap; }
  fieldset { border: 1px solid rgba(128,128,128,.4); border-radius: 6px; padding: 1rem; }
  button { padding: .5rem 1rem; font: inherit; cursor: pointer; }
</style>
<h1>Complaint Processing API</h1>
<p>Upload one complaint document (<code>.txt</code>, <code>.pdf</code> or
   <code>.docx</code>) to get its structured extraction, customer email and
   internal case summary.</p>
<form id="f">
  <fieldset>
    <input type="file" name="file" accept=".txt,.pdf,.docx" required>
    <button>Process</button>
  </fieldset>
</form>
<pre id="out">Results appear here.</pre>
<p>Endpoints: <code>GET /api/health</code>, <code>GET /api/samples</code>,
   <code>POST /api/process</code>, <code>POST /api/process/sample/{name}</code>.</p>
<script>
  const f = document.getElementById('f'), out = document.getElementById('out');
  f.onsubmit = async (e) => {
    e.preventDefault();
    out.textContent = 'Processing, this takes a few seconds...';
    try {
      const r = await fetch('/api/process', { method: 'POST', body: new FormData(f) });
      out.textContent = JSON.stringify(await r.json(), null, 2);
    } catch (err) {
      out.textContent = 'Request failed: ' + err;
    }
  };
</script>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML
