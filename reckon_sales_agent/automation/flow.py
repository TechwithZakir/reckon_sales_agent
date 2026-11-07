"""The automation flow: a small graph of steps that people move through (pure: no Frappe imports).

A flow is JSON: ``{"start": "n1", "nodes": {"n1": {"type": "trigger", "config": {...}, "next": "n2"}, ...}}``. A step has
one exit (``next``), except a condition, which has two (``yes`` and ``no``). A missing exit ends the flow for that person.

Step types: trigger (what starts it), send (an approved template on Email, SMS or WhatsApp), wait, condition (opened,
clicked, replied, has a tag, is in a segment, is confirmed), action (tag, task, notify, change a field, stop) and webhook.

The browser edits this JSON, so the server never trusts it: ``normalize`` rebuilds it from known parts only, and ``issues``
says in plain words what must be fixed before the automation can be switched on.
"""

from __future__ import annotations

import re

from reckon_sales_agent.campaigns import tags as tag_rules

MAX_NODES = 60
TRIGGERS = {
    "signup": "Someone signs up on a form",
    "tag_added": "A tag is added to someone",
    "segment_joined": "Someone joins a segment",
    "deal_stage": "A CRM deal changes stage",
    "reply_received": "Someone replies to a message",
    "api_call": "Your system calls the API",
    "manual": "You enrol people by hand",
}
CHECKS = {
    "opened": "opened the email", "clicked": "clicked a link", "replied": "replied",
    "tag": "has the tag", "segment": "is in the segment", "confirmed": "has confirmed their email",
}
EVENT_CHECKS = ("opened", "clicked", "replied")
ACTIONS = {
    "add_tag": "Add a tag", "remove_tag": "Remove a tag", "create_task": "Create a CRM task",
    "notify": "Notify the owner", "set_city": "Set the city", "set_industry": "Set the industry", "stop": "Stop here",
}
WAIT_UNITS = {"minutes": 1, "hours": 60, "days": 1440}
WAIT_LIMITS = {"minutes": 10080, "hours": 8760, "days": 365}
TYPES = ("trigger", "send", "wait", "condition", "action", "webhook")
_ID = re.compile(r"^[a-z0-9_]{1,20}$")


def _text(value, longest: int = 140) -> str:
    return " ".join(str(value or "").split())[:longest]


def _https(value) -> str:
    text = str(value or "").strip()
    return text if text.lower().startswith("https://") and len(text) <= 500 and not re.search(r"[\s\"'<>]", text) else ""


def clean_config(kind: str, raw) -> dict:
    """The known settings of one step, cleaned. Anything else in ``raw`` is dropped."""
    raw = raw if isinstance(raw, dict) else {}
    if kind == "trigger":
        event = raw.get("event") if raw.get("event") in TRIGGERS else "signup"
        return {"event": event, "form": _text(raw.get("form"), 60), "tag": tag_rules.clean(raw.get("tag")),
                "segment": _text(raw.get("segment")), "status": _text(raw.get("status")),
                "reenter": bool(raw.get("reenter"))}
    if kind == "send":
        return {"template": _text(raw.get("template"))}
    if kind == "wait":
        unit = raw.get("unit") if raw.get("unit") in WAIT_UNITS else "days"
        try:
            amount = int(float(raw.get("amount")))
        except (TypeError, ValueError):
            amount = 1
        return {"amount": max(1, min(amount, WAIT_LIMITS[unit])), "unit": unit}
    if kind == "condition":
        check = raw.get("check") if raw.get("check") in CHECKS else "opened"
        try:
            wait_days = int(float(raw.get("wait_days") or 0))
        except (TypeError, ValueError):
            wait_days = 0
        return {"check": check, "ref": raw.get("ref") if _ID.match(str(raw.get("ref") or "")) else "any",
                "wait_days": max(0, min(wait_days, 30)), "tag": tag_rules.clean(raw.get("tag")),
                "segment": _text(raw.get("segment"))}
    if kind == "action":
        do = raw.get("do") if raw.get("do") in ACTIONS else "add_tag"
        return {"do": do, "value": tag_rules.clean(raw.get("value")) if do in ("add_tag", "remove_tag")
                else _text(raw.get("value"), 140)}
    if kind == "webhook":
        return {"url": _https(raw.get("url"))}
    return {}


def _exit(raw, ids, key: str):
    target = raw.get(key)
    return target if isinstance(target, str) and target in ids else None


def normalize(flow) -> dict:
    """A clean copy: known step types, valid ids, exits that point at real steps, at most 60 steps, only what the start
    reaches. An unusable flow becomes an empty one with just a trigger."""
    nodes_in = flow.get("nodes") if isinstance(flow, dict) and isinstance(flow.get("nodes"), dict) else {}
    ids = [i for i in list(nodes_in)[:MAX_NODES * 2] if _ID.match(str(i)) and isinstance(nodes_in[i], dict)
           and nodes_in[i].get("type") in TYPES]
    start = flow.get("start") if isinstance(flow, dict) else None
    if start not in ids or nodes_in[start].get("type") != "trigger":
        start = next((i for i in ids if nodes_in[i].get("type") == "trigger"), None)
    if start is None:
        return new_flow()
    out: dict = {}
    queue = [start]
    while queue and len(out) < MAX_NODES:
        node_id = queue.pop(0)
        if node_id in out:
            continue
        raw = nodes_in[node_id]
        kind = raw["type"]
        if kind == "trigger" and node_id != start:
            continue  # one trigger only
        node = {"type": kind, "config": clean_config(kind, raw.get("config"))}
        if kind == "condition":
            node["yes"], node["no"] = _exit(raw, ids, "yes"), _exit(raw, ids, "no")
            exits = [node["yes"], node["no"]]
        else:
            node["next"] = _exit(raw, ids, "next")
            exits = [node["next"]]
        out[node_id] = node
        queue.extend(e for e in exits if e)
    for node in out.values():  # exits to steps that were dropped
        for key in ("next", "yes", "no"):
            if node.get(key) and node[key] not in out:
                node[key] = None
    return {"version": 1, "start": start, "nodes": out}


def new_flow(event: str = "signup") -> dict:
    return {"version": 1, "start": "n1", "nodes": {"n1": {"type": "trigger", "config": clean_config("trigger", {"event": event}),
                                                         "next": None}}}


def exits(node: dict) -> list[str]:
    return [t for t in ((node.get("yes"), node.get("no")) if node.get("type") == "condition" else (node.get("next"),)) if t]


def order(flow: dict) -> list[str]:
    """Step ids in reading order: depth first from the trigger, the Yes branch before the No branch."""
    seen: list[str] = []

    def visit(node_id):
        if not node_id or node_id in seen or node_id not in flow.get("nodes", {}):
            return
        seen.append(node_id)
        for target in exits(flow["nodes"][node_id]):
            visit(target)

    visit(flow.get("start"))
    return seen


def send_nodes(flow: dict) -> list[str]:
    return [i for i in order(flow) if flow["nodes"][i]["type"] == "send"]


def has_cycle(flow: dict) -> bool:
    nodes = flow.get("nodes", {})
    state: dict[str, int] = {}

    def visit(node_id) -> bool:
        if state.get(node_id) == 1:
            return True
        if state.get(node_id) == 2:
            return False
        state[node_id] = 1
        found = any(visit(t) for t in exits(nodes.get(node_id, {})) if t in nodes)
        state[node_id] = 2
        return found

    return visit(flow.get("start"))


def ancestors(flow: dict, node_id: str) -> set[str]:
    """Every step that can lead to ``node_id``."""
    found: set[str] = set()
    changed = True
    while changed:
        changed = False
        for other, node in flow.get("nodes", {}).items():
            if other not in found and any(t == node_id or t in found for t in exits(node)):
                found.add(other)
                changed = True
    return found


def issues(flow: dict, template_status=None) -> list[dict]:
    """What must be fixed before the automation can be switched on: [{"node": id, "message": text}].

    ``template_status`` maps a template name to (channel, status) for the Company, or None when unknown.
    """
    problems: list[dict] = []

    def add(node_id, message):
        problems.append({"node": node_id, "message": message})

    nodes = flow.get("nodes", {})
    if flow.get("start") not in nodes:
        return [{"node": "", "message": "The flow has no trigger."}]
    if has_cycle(flow):
        add(flow["start"], "The flow loops back on itself. Steps must always move forward.")
    reachable = set(order(flow))
    for node_id in order(flow):
        node, cfg = nodes[node_id], nodes[node_id]["config"]
        kind = node["type"]
        if kind == "trigger":
            event = cfg.get("event")
            if event == "tag_added" and not cfg.get("tag"):
                add(node_id, "Choose the tag that starts this automation.")
            if event == "segment_joined" and not cfg.get("segment"):
                add(node_id, "Choose the segment that starts this automation.")
        elif kind == "send":
            if not cfg.get("template"):
                add(node_id, "Choose a template to send.")
            elif template_status is not None:
                found = template_status(cfg["template"])
                if not found:
                    add(node_id, "That template does not exist.")
                elif found[1] != "Approved":
                    add(node_id, "That template is not approved yet.")
                elif found[0] not in ("Email", "SMS", "WhatsApp"):
                    add(node_id, "Only Email, SMS and WhatsApp templates can be sent here.")
        elif kind == "condition":
            if cfg["check"] in EVENT_CHECKS and cfg["ref"] != "any":
                if cfg["ref"] not in ancestors(flow, node_id) or nodes.get(cfg["ref"], {}).get("type") != "send":
                    add(node_id, "Choose a message that is sent earlier in this flow.")
            if cfg["check"] in EVENT_CHECKS and cfg["ref"] == "any" and not any(
                    nodes[a]["type"] == "send" for a in ancestors(flow, node_id)):
                add(node_id, "Nothing has been sent before this step, so there is nothing to check.")
            if cfg["check"] == "tag" and not cfg.get("tag"):
                add(node_id, "Choose the tag to check.")
            if cfg["check"] == "segment" and not cfg.get("segment"):
                add(node_id, "Choose the segment to check.")
            if not node.get("yes") and not node.get("no"):
                add(node_id, "Add a step to the Yes or the No path.")
        elif kind == "action":
            if cfg["do"] in ("add_tag", "remove_tag") and not cfg.get("value"):
                add(node_id, "Enter the tag.")
            if cfg["do"] in ("set_city", "set_industry", "create_task") and not cfg.get("value"):
                add(node_id, "Enter a value.")
        elif kind == "webhook":
            if not cfg.get("url"):
                add(node_id, "Enter the address to call (it must start with https://).")
    if not any(nodes[i]["type"] in ("send", "action", "webhook") for i in reachable):
        add(flow["start"], "Add at least one step after the trigger.")
    return problems


def wait_minutes(config: dict) -> int:
    return int(config.get("amount") or 1) * WAIT_UNITS.get(config.get("unit"), 1440)


def describe(node: dict) -> str:
    """One line for a step card."""
    kind, cfg = node.get("type"), node.get("config") or {}
    if kind == "trigger":
        text = TRIGGERS.get(cfg.get("event"), "Starts here")
        extra = cfg.get("form") or cfg.get("tag") or cfg.get("segment") or cfg.get("status")
        return f"{text}: {extra}" if extra else text
    if kind == "send":
        return f"Send {cfg.get('template') or 'a template'}"
    if kind == "wait":
        return f"Wait {cfg.get('amount', 1)} {cfg.get('unit', 'days')}"
    if kind == "condition":
        text = f"If they {CHECKS.get(cfg.get('check'), '?')}"
        extra = cfg.get("tag") if cfg.get("check") == "tag" else cfg.get("segment") if cfg.get("check") == "segment" else ""
        text = f"{text} {extra}".strip()
        return f"{text}, deciding after {cfg['wait_days']} days" if cfg.get("wait_days") and cfg.get("check") in EVENT_CHECKS else text
    if kind == "action":
        label = ACTIONS.get(cfg.get("do"), "Action")
        return f"{label}: {cfg['value']}" if cfg.get("value") else label
    if kind == "webhook":
        return f"Call {cfg.get('url') or 'a web address'}"
    return kind or ""


def walk(flow: dict, decisions: dict | None = None) -> list[dict]:
    """The path one person takes, for the simulator: every step with the time since they entered. ``decisions`` says,
    per condition id, whether the answer is Yes (default Yes). Nothing is sent or changed."""
    decisions = decisions or {}
    path: list[dict] = []
    nodes = flow.get("nodes", {})
    node_id = flow.get("start")
    elapsed = 0
    guard = 0
    while node_id in nodes and guard < MAX_NODES + 5:
        guard += 1
        node = nodes[node_id]
        kind = node["type"]
        if kind == "wait":
            elapsed += wait_minutes(node["config"])
        if kind == "condition" and node["config"].get("wait_days") and node["config"]["check"] in EVENT_CHECKS \
                and not decisions.get(node_id, True):
            elapsed += node["config"]["wait_days"] * 1440  # waits the whole window, then answers No
        answer = None
        if kind == "condition":
            answer = bool(decisions.get(node_id, True))
            target = node.get("yes") if answer else node.get("no")
        elif kind == "action" and node["config"].get("do") == "stop":
            path.append({"node": node_id, "type": kind, "label": describe(node), "after_minutes": elapsed, "answer": None})
            break
        else:
            target = node.get("next")
        path.append({"node": node_id, "type": kind, "label": describe(node), "after_minutes": elapsed, "answer": answer})
        node_id = target
    return path


def duration_text(minutes: int) -> str:
    """'now', '30 min', '2 hours', '3 days'."""
    if minutes <= 0:
        return "now"
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 1440:
        hours = minutes / 60
        return f"{hours:g} hours" if hours != 1 else "1 hour"
    days = minutes / 1440
    return f"{days:g} days" if days != 1 else "1 day"
