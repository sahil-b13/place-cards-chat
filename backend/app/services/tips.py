"""Short tips for a finished plan. The AI only rephrases facts we give it; every number it uses must
already appear in the plan/facts, otherwise we discard its output and use template tips."""
import json
import re
from typing import Optional

import httpx

from .vision import ANTHROPIC_URL, ANTHROPIC_VERSION

MAX_TIPS = 4
MAX_TIP_LEN = 160
_NUM = re.compile(r"\d+(?:\.\d+)?")

SYSTEM = (
    "You write up to 4 very short travel tips (max 140 characters each) for a one-day plan. "
    "Use ONLY the facts in the JSON provided. Do NOT add any number, time, price, distance or opening hour "
    "that is not in the JSON. No links. Reply with a JSON array of strings and nothing else."
)


def numbers_in(obj) -> set[str]:
    """Normalised numeric tokens in any JSON-able object ('08:25' -> {'8','25'}, '6.20' -> '6.2')."""
    out = set()
    for tok in _NUM.findall(json.dumps(obj, ensure_ascii=False)):
        out.add(_norm(tok))
    return out


def _norm(tok: str) -> str:
    if "." in tok:
        a, b = tok.split(".", 1)
        b = b.rstrip("0")
        return str(int(a)) + ("." + b if b else "")
    return str(int(tok))


def tip_is_safe(tip: str, allowed: set[str]) -> bool:
    if not isinstance(tip, str) or not tip.strip() or len(tip) > MAX_TIP_LEN:
        return False
    if re.search(r"https?://|www\.", tip, re.I):
        return False
    return all(_norm(t) in allowed for t in _NUM.findall(tip))


def template_tips(plan: dict, facts: dict) -> list[str]:
    tips: list[str] = []
    days = plan.get("days") or []
    first = days[0]["stops"][0] if days and days[0].get("stops") else None
    for w in plan.get("traffic_windows") or []:
        if w.get("level") == "heavy":
            tips.append(f"Heavy traffic is likely {w['from']}-{w['to']}; plan to be between stops outside that window.")
            break
    if facts.get("best_departure"):
        tips.append(f"Traffic is lightest around {facts['best_departure']} (modelled estimate).")
    lunch = days[0].get("lunch") if days else None
    if lunch:
        tips.append(f"Lunch at {lunch['name']} around {lunch['arrive']}.")
    cost = plan.get("cost") or {}
    if cost.get("total") is not None:
        tips.append(f"Estimated total {cost['total']} {cost.get('currency', '')}, about {cost['per_person']} per person.")
    if first and len(tips) < MAX_TIPS:
        tips.append(f"Start at {plan.get('start_time')} to reach {first['name']} at {first['arrive']}.")
    return tips[:MAX_TIPS]


def _compact(plan: dict) -> dict:
    return {
        "plan_type": plan.get("plan_type"), "start_time": plan.get("start_time"),
        "stops": [{"order": s["order"], "name": s["name"], "arrive": s["arrive"], "depart": s["depart"]}
                  for d in plan.get("days", []) for s in d.get("stops", [])],
        "lunch": [d["lunch"] for d in plan.get("days", []) if d.get("lunch")],
        "traffic_windows": plan.get("traffic_windows"), "cost": plan.get("cost"),
        "warnings": plan.get("warnings"),
    }


async def make_tips(plan: dict, facts: dict, llm=None) -> list[str]:
    fallback = template_tips(plan, facts)
    if llm is None:
        return fallback
    payload = {"plan": _compact(plan), "facts": facts}
    allowed = numbers_in(payload)
    try:
        raw = await llm.complete(SYSTEM, json.dumps(payload, ensure_ascii=False))
        m = re.search(r"\[.*\]", raw or "", re.DOTALL)
        arr = json.loads(m.group(0)) if m else None
        if not isinstance(arr, list):
            return fallback
        tips = [t.strip() for t in arr if isinstance(t, str)][:MAX_TIPS]
        if not tips or not all(tip_is_safe(t, allowed) for t in tips):
            return fallback
        return tips
    except Exception:
        return fallback


class AnthropicText:
    def __init__(self, api_key: str, model: str, timeout: float = 15.0, transport=None):
        self.api_key, self.model, self.timeout, self._transport = api_key, model, timeout, transport

    async def complete(self, system: str, user: str) -> str:
        body = {"model": self.model, "max_tokens": 400, "system": system,
                "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as c:
            r = await c.post(ANTHROPIC_URL, headers=headers, json=body)
        r.raise_for_status()
        return "".join(p.get("text", "") for p in r.json().get("content", []) if p.get("type") == "text")


class GeminiText:
    BASE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str, timeout: float = 15.0, transport=None):
        self.api_key, self.model, self.timeout, self._transport = api_key, model, timeout, transport

    async def complete(self, system: str, user: str) -> str:
        body = {"system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"response_mime_type": "application/json", "temperature": 0.2}}
        headers = {"x-goog-api-key": self.api_key, "content-type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as c:
            r = await c.post(self.BASE.format(model=self.model), headers=headers, json=body)
        r.raise_for_status()
        parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts if isinstance(p.get("text"), str))


def build_text_llm(provider: str, gemini_api_key="", gemini_model="", anthropic_api_key="", vision_model="") -> Optional[object]:
    if provider == "gemini" and gemini_api_key and gemini_model:
        return GeminiText(gemini_api_key, gemini_model)
    if provider == "anthropic" and anthropic_api_key:
        return AnthropicText(anthropic_api_key, vision_model or "claude-haiku-5-5")
    return None
