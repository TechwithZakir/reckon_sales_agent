"""A Model Context Protocol (MCP) endpoint, so an AI assistant (Claude, ChatGPT, Cursor ...) can work in Campaign Studio.

Streamable HTTP, stateless, JSON-RPC 2.0. Authenticate with the header ``Authorization: token <api_key>:<api_secret>`` of a Sales
Agent manager; the assistant then sees and changes only that user's Company, and only what the tools below allow.

The assistant can look, count, draft and tag. It can NOT send, approve, switch an automation on, import files or delete
anything: those decisions stay with a person in the Studio.

    URL: https://YOUR-SITE/api/method/reckon_sales_agent.api_mcp.rpc
"""

from __future__ import annotations

import json

import frappe
from werkzeug.wrappers import Response

from reckon_sales_agent import (
    api_automation,
    api_campaign_studio,
    api_public,
    api_segments,
    api_verify,
)
from reckon_sales_agent.api_studio import _can_manage

PROTOCOL = "2025-03-26"
SERVER = {"name": "reckon-sales-agent", "version": "1.0.0"}
READ_ONLY = {"readOnlyHint": True}
OBJECT = {"type": "object"}


def _schema(**props) -> dict:
    required = [k for k, v in props.items() if v.pop("required", False)]
    return {"type": "object", "properties": props, "required": required}


def _text(**extra) -> dict:
    return {"type": "string", **extra}


TOOLS = {
    "list_segments": ("List the saved segments with how many people each holds.", _schema(), lambda a: api_public.segments(), True),
    "preview_segment": ("Count and sample the people a set of rules matches, without saving. A rule is {field, op, value}; fields: "
                        "joined, opened, clicked, replied, sent, tag, city, industry, source, fit_score, has_email, has_phone, sms_consent, "
                        "whatsapp_consent, confirmed, temperature, email_check.",
                        _schema(rules={"type": "array", "items": {"type": "object"}, "required": True}, match_mode=_text(enum=["All", "Any"])),
                        lambda a: api_segments.preview(a.get("rules") or [], a.get("match_mode") or "All"), True),
    "save_segment": ("Save a segment (rules as in preview_segment). Needs a manager.",
                     _schema(segment_name=_text(required=True), rules={"type": "array", "items": {"type": "object"}, "required": True},
                             match_mode=_text(enum=["All", "Any"]), description=_text()),
                     lambda a: api_segments.save_segment({"segment_name": a.get("segment_name"), "rules": a.get("rules") or [],
                                                          "match_mode": a.get("match_mode") or "All", "description": a.get("description")}), False),
    "list_forms": ("List the signup forms with their signups.", _schema(), lambda a: api_public.forms(), True),
    "list_automations": ("List the automations with their status.", _schema(), lambda a: api_public.automations(), True),
    "automation_report": ("How many people reached each step of an automation, and where they are now.",
                          _schema(name=_text(required=True)), lambda a: api_automation.automation(a["name"])["stats"], True),
    "simulate_automation": ("Follow one imaginary person through an automation and say what happens when. Nothing is sent.",
                            _schema(name=_text(required=True)),
                            lambda a: api_automation.simulate(api_automation.automation(a["name"])["flow"]), True),
    "find_person": ("One person by email or phone: tags, engagement, whether they confirmed and whether the address checks out.",
                    _schema(email=_text(), phone=_text()), lambda a: api_public.person(a.get("email") or "", a.get("phone") or ""), True),
    "tag_person": ("Add or remove tags on one person. Needs a manager.", _schema(email=_text(required=True), add=_text(), remove=_text()),
                   lambda a: api_public.person_tags(a["email"], "", a.get("add") or "", a.get("remove") or ""), False),
    "list_campaigns": ("List campaigns with their results.", _schema(), lambda a: api_campaign_studio.campaigns(), True),
    "campaign_report": ("The funnel and results of one campaign.", _schema(name=_text(required=True)),
                        lambda a: api_campaign_studio.campaign(a["name"])["metrics"], True),
    "list_hygiene": ("How many addresses are Valid, Risky, Invalid or not checked yet.", _schema(), lambda a: api_verify.summary(), True),
    "check_email": ("Check one address: Valid, Risky or Invalid, and why.", _schema(email=_text(required=True)),
                    lambda a: api_public.check_email(a["email"]), True),
}


def _tools_list() -> list[dict]:
    return [{"name": name, "description": description, "inputSchema": schema, "annotations": {"readOnlyHint": read_only}}
            for name, (description, schema, _fn, read_only) in TOOLS.items()]


def _call(name: str, arguments: dict) -> dict:
    if name not in TOOLS:
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
    _description, _schema_, function, read_only = TOOLS[name]
    try:
        if not read_only and not _can_manage():
            raise frappe.PermissionError("This tool needs a Sales Agent admin or manager.")
        result = function(arguments if isinstance(arguments, dict) else {})
        return {"content": [{"type": "text", "text": json.dumps(result, default=str, ensure_ascii=False)[:60000]}], "isError": False}
    except Exception as exc:
        message = (str(exc) or type(exc).__name__)[:500]
        return {"content": [{"type": "text", "text": message}], "isError": True}


def handle(request: dict) -> dict | None:
    """One JSON-RPC message in, the answer out (None for a notification, which has no answer)."""
    method, ident = request.get("method"), request.get("id")
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    if ident is None and str(method or "").startswith("notifications/"):
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL, "capabilities": {"tools": {}}, "serverInfo": SERVER,
                   "instructions": "Tools for Campaign Studio: segments, forms, automations, people and reports. They never send, approve or delete."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": _tools_list()})
    if method == "tools/call":
        return ok(_call(str(params.get("name") or ""), params.get("arguments") or {}))
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"Method not found: {method}"}}


@frappe.whitelist(methods=["POST"])
def rpc():
    """The MCP endpoint. A signed-in user (an API key) is required; the answer is plain JSON-RPC."""
    try:
        body = json.loads(frappe.request.get_data() or b"{}")
    except ValueError:
        return Response(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}),
                        status=400, mimetype="application/json")
    messages = body if isinstance(body, list) else [body]
    answers = [a for a in (handle(m) if isinstance(m, dict) else None for m in messages) if a is not None]
    if not answers:
        return Response("", status=202)
    return Response(json.dumps(answers if isinstance(body, list) else answers[0], default=str, ensure_ascii=False), mimetype="application/json")
