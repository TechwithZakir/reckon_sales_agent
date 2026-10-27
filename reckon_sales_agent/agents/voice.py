"""Voice agent: after a recorded office-phone call, a transcript and an AI summary on the CRM call log.

When the PBX reports a completed call with a recording, the agent downloads the recording (from the Company's own
PBX, with its credentials, or from a public address), has it transcribed (Bangla and English) by the speech-to-text
service the system provider set (OpenAI, or a local OpenAI-compatible Whisper server), and asks the Company's AI for
a summary, the likely outcome, the next step and one coaching tip. All of it becomes a note on the call log. The
outcome stays the salesperson's click; the suggestion only saves typing.

Callers must hear a recording notice before a recorded call (see docs/telephony-asterisk.md).
``summary_prompt`` is pure.
"""

from __future__ import annotations

from urllib.parse import urlsplit

MAX_BYTES = 25 * 1024 * 1024  # the transcription APIs' upload limit
OUTCOMES = ("interested", "callback", "not_interested", "no_answer", "wrong_number", "unclear")
SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "outcome": {"type": "string", "enum": list(OUTCOMES)},
                   "next_step": {"type": "string"}, "coaching": {"type": "string"}},
    "required": ["summary", "outcome", "next_step", "coaching"], "additionalProperties": False,
}
SYSTEM = ("You summarise a sales call of a B2B seller in Bangladesh from its transcript (Bangla or English). "
          "summary: 3-5 short bullet lines in English of what the customer said and wants. outcome: the most likely "
          "result. next_step: one concrete action with a date if one was agreed. coaching: one specific, kind tip "
          "for the salesperson. Use only what is in the transcript.")


def summary_prompt(transcript: str, lead: str) -> str:
    from reckon_sales_agent.providers.llm import untrusted

    return untrusted("lead", lead) + "\n" + untrusted("call transcript", transcript[:20000])


def same_host(url: str, other: str | None) -> bool:
    return bool(other) and urlsplit(url).hostname == urlsplit(other).hostname


# --------------------------------------------------------------------------- Frappe side


def queue(call_log: str) -> None:
    import frappe

    frappe.enqueue("reckon_sales_agent.agents.voice.summarize_call", queue="long", call_log=call_log,
                   job_id=f"voice:{call_log}", deduplicate=True, enqueue_after_commit=True)


def _recording(company: str, url: str) -> bytes:
    import frappe
    import requests

    from reckon_sales_agent.research.url_safety import UnsafeURL, validate_url
    from reckon_sales_agent.usage import get_settings

    settings = get_settings(company)
    auth = None
    if same_host(url, settings.get("ari_url")):
        # The Company's own PBX (often on its private network): its credentials, its address.
        auth = (settings.get("ari_username") or "", settings.get_password("ari_password", raise_exception=False) or "")
    else:
        try:
            validate_url(url)
        except UnsafeURL:
            frappe.throw("The recording is not on a public address or the Company's phone system.")
    response = requests.get(url, auth=auth, timeout=60, stream=True)
    response.raise_for_status()
    data = b""
    for chunk in response.iter_content(65536):
        data += chunk
        if len(data) > MAX_BYTES:
            frappe.throw("The recording is longer than the transcription service accepts (25 MB).")
    return data


def _transcribe(audio: bytes) -> str:
    import frappe
    import requests

    from reckon_sales_agent.usage import platform_settings

    platform = platform_settings()
    if not platform.get("transcription_enabled"):
        frappe.throw("Call transcription is off (system provider setting).")
    local = platform.get("transcription_provider") == "Local (OpenAI-compatible)"
    base = (platform.get("local_ai_base_url") if local else platform.get("openai_base_url")) or "https://api.openai.com/v1"
    field = "local_ai_api_key" if local else "openai_api_key"
    key = platform.get_password(field, raise_exception=False) if platform.get(field) else None
    response = requests.post(f"{base.rstrip('/')}/audio/transcriptions",
                             headers={"Authorization": f"Bearer {key}"} if key else {},
                             files={"file": ("call.wav", audio)},
                             data={"model": platform.get("transcription_model") or "whisper-1"}, timeout=300)
    if response.status_code >= 400:
        from reckon_sales_agent.providers.llm import http_reason

        frappe.throw(f"Transcription failed: {http_reason(response)}")
    return str((response.json() or {}).get("text") or "").strip()


def summarize_call(call_log: str) -> str | None:
    import frappe

    from reckon_sales_agent.constants import USAGE_AI
    from reckon_sales_agent.providers.factory import get_llm
    from reckon_sales_agent.providers.llm import LLMError
    from reckon_sales_agent.usage import log_activity, reserve

    log = frappe.get_doc("CRM Call Log", call_log)
    company = log.get("rsa_company")
    if not company or not log.recording_url or log.get("note"):
        return None
    transcript = _transcribe(_recording(company, log.recording_url))
    if not transcript:
        return None
    lead = f"{log.reference_doctype or ''} {log.reference_docname or ''}"
    data = {"summary": "", "outcome": "unclear", "next_step": "", "coaching": ""}
    llm = get_llm(company)
    if llm:
        reserve(company, USAGE_AI, 1, log)
        try:
            data = llm.complete_json(SYSTEM, summary_prompt(transcript, lead), SCHEMA, max_tokens=1200)
        except LLMError:
            pass
    esc = frappe.utils.escape_html
    content = (f"<p><b>Suggested outcome:</b> {esc(data['outcome'].replace('_', ' '))}</p>"
               f"<p><b>Summary</b><br>{esc(data['summary']).replace(chr(10), '<br>')}</p>"
               f"<p><b>Next step:</b> {esc(data['next_step'])}</p><p><b>Coaching:</b> {esc(data['coaching'])}</p>"
               f"<details><summary>Transcript</summary>{esc(transcript).replace(chr(10), '<br>')}</details>")
    note = frappe.get_doc({"doctype": "FCRM Note", "title": "Call summary", "content": content,
                           "reference_doctype": log.reference_doctype if log.reference_doctype == "CRM Lead" else None,
                           "reference_docname": log.reference_docname if log.reference_doctype == "CRM Lead" else None})
    if frappe.get_meta("FCRM Note").has_field("rsa_company"):
        note.rsa_company = company
    note.insert(ignore_permissions=True)
    frappe.db.set_value("CRM Call Log", log.name, "note", note.name, update_modified=False)
    log_activity(company, "call_summarized", log, f"Suggested outcome: {data['outcome']}. {data['next_step']}"[:500],
                 actor_type="agent", agent="Engagement", policy_outcome="automatic (notes only)")
    frappe.db.commit()
    return note.name
