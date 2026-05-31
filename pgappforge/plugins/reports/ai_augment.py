"""
ReportForge AI text augmentation — generates/rewrites report text via Ollama.

Uses the same Ollama connection as app_creator_chat.py.
Config keys (from Flask app):
    PGAF_OLLAMA_URL   default "http://localhost:11434"
    PGAF_OLLAMA_MODEL default "granite4.1:8b"
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a professional business writer producing text for formal business reports. "
    "Write concise, polished prose. No markdown, no bullet points unless explicitly asked. "
    "Return ONLY the requested text — no preamble, no explanation."
)


def _ollama_url(app) -> str:
    return app.config.get("PGAF_OLLAMA_URL", "http://localhost:11434")


def _ollama_model(app) -> str:
    return app.config.get("PGAF_OLLAMA_MODEL", "granite4.1:8b")


def augment_text(
    prompt: str,
    context: dict[str, Any],
    app: Any,
    max_tokens: int = 400,
) -> str:
    """
    Generate or rewrite report text using the local Ollama model.

    Args:
        prompt: user instruction, e.g. "Write a 2-sentence cover letter for this invoice."
        context: dict with report metadata to inject (report_name, company_name, etc.)
        app: Flask app for config access.
        max_tokens: token budget for the completion.

    Returns:
        Generated text string, or error message prefixed with "Error:".
    """
    try:
        import requests
    except ImportError:
        return "Error: requests library not available."

    ctx_lines = "\n".join(f"  {k}: {v}" for k, v in context.items() if v)
    full_prompt = (
        f"Report context:\n{ctx_lines}\n\n"
        f"Task: {prompt}"
    ) if ctx_lines else prompt

    payload = {
        "model":  _ollama_model(app),
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.7},
        "messages": [
            {"role": "system",  "content": _SYSTEM},
            {"role": "user",    "content": full_prompt},
        ],
    }
    try:
        resp = requests.post(
            f"{_ollama_url(app)}/api/chat",
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "").strip()
    except Exception as exc:
        log.warning("ReportForge AI augment failed: %s", exc)
        return f"Error: {exc}"


def suggest_report_title(report_name: str, sql: str, app: Any) -> str:
    return augment_text(
        f"Suggest a professional title for a business report named '{report_name}' "
        f"that runs this SQL query:\n{sql[:400]}\n\nReturn just the title, nothing else.",
        {}, app, max_tokens=50,
    )


def generate_cover_paragraph(
    report_name: str,
    company_name: str | None,
    template_key: str | None,
    app: Any,
) -> str:
    tmpl_labels = {
        "invoice": "sales invoice",
        "quote": "customer quotation",
        "statement": "statement of account",
        "business_letter": "business letter",
        "tabular": "data report",
        "summary": "executive summary",
    }
    doc_type = tmpl_labels.get(template_key or "", "business report")
    context = {"Company": company_name or "the company", "Document type": doc_type}
    return augment_text(
        f"Write a single professional paragraph (3–4 sentences) as an introduction "
        f"for a {doc_type} titled '{report_name}'. It should explain the purpose "
        f"of the document and encourage the recipient to contact us with questions.",
        context, app,
    )
