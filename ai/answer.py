"""The assistant's answer format, and the check that every amount and percentage in an answer comes from the
app's own figures.

Every answer has the same parts, so it reads the same way each time: a direct answer, what the data shows, what to
do next (only when useful), an optional draft, the sources used and two follow-up questions.
"""
from __future__ import annotations

import re
from typing import Dict, List

SOURCES = ["Receivables report", "Request queue", "Process measures"]

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string",
                   "description": "One or two sentences that directly answer the question, with the key figure."},
        "findings": {"type": "array", "items": {"type": "string"},
                     "description": "Up to four short facts from the data, each with its figure."},
        "next_steps": {"type": "array", "items": {"type": "string"},
                       "description": "Up to three practical actions for a person, or none."},
        "draft": {"type": "string",
                  "description": "Only when asked to write something: the full text. Otherwise empty."},
        "sources": {"type": "array", "items": {"type": "string", "enum": SOURCES}},
        "follow_ups": {"type": "array", "items": {"type": "string"},
                       "description": "Two short follow-up questions the same data can answer."},
    },
    "required": ["answer", "findings", "next_steps", "draft", "sources", "follow_ups"],
    "additionalProperties": False,
}

FORMAT_RULES = """Reply in JSON with exactly these fields:
- answer: one or two sentences that directly answer the question, leading with the single most important figure. No preamble.
- findings: up to four short sentences on what the data shows. Each has one figure and names where it comes from (for example "Overdue balance by billing category"). No advice here.
- next_steps: up to three practical actions a person could take, each starting with a verb. Give them only when the question asks what to do, or a clear action follows from the findings; otherwise an empty list.
- draft: only when the visitor asks you to write or draft something (an update, a summary, an email). The full text, under 150 words, in plain sentences, ready to review. Otherwise an empty string.
- sources: which of "Receivables report", "Request queue" and "Process measures" you used.
- follow_ups: two short questions the visitor could ask next that the same data can answer.
If the data does not answer the question, say so in answer, name the data that would be needed, and leave findings and next_steps empty.
Money: copy amounts exactly as they appear in the summaries. For amounts of $100,000 or more use the short form shown in brackets, for example $4.92M. Percentages: copy them exactly; never work out a new percentage."""

_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)(?:\s?(million|thousand|[MK])\b)?", re.I)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s?%")
_SCALE = {"m": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}


def _decimals(number: str) -> int:
    return len(number.split(".")[1]) if "." in number else 0


def _money(text: str):
    for m in _MONEY.finditer(text):
        number, unit = m.group(1).replace(",", ""), (m.group(2) or "").lower()
        try:
            yield m.group(0).strip(), float(number), _decimals(number), _SCALE.get(unit, 1.0)
        except ValueError:
            continue


def _known(context: str):
    money = [value * scale for _, value, _, scale in _money(context)]
    pct = [float(p) for p in _PCT.findall(context)]
    return money, pct


def unmatched(answer_text: str, context: str) -> List[str]:
    """Amounts and percentages in the answer that do not appear in the context, allowing the short forms
    ($4.92M, $579K) of a context figure. Counts and days are not checked."""
    money, pct = _known(context)
    bad: List[str] = []
    for token, value, places, scale in _money(answer_text):
        ok = any(round(known / scale, places) == round(value, places) for known in money) if scale != 1.0 else \
            any(abs(known - value) < 0.01 or (places == 0 and abs(known - value) < 1) for known in money)
        if not ok and token not in bad:
            bad.append(token)
    for number in _PCT.findall(answer_text):
        places = _decimals(number)
        if not any(round(known, places) == round(float(number), places) for known in pct):
            token = f"{number}%"
            if token not in bad:
                bad.append(token)
    return bad


def clean(data: Dict) -> Dict:
    """Keep the expected fields, with sensible limits, whatever the model returned."""
    def strings(value, limit):
        items = value if isinstance(value, list) else ([value] if value else [])
        return [str(v).strip() for v in items if str(v).strip()][:limit]
    return {
        "answer": str(data.get("answer") or "").strip(),
        "findings": strings(data.get("findings"), 4),
        "next_steps": strings(data.get("next_steps"), 3),
        "draft": str(data.get("draft") or "").strip(),
        "sources": [s for s in strings(data.get("sources"), 3) if s in SOURCES],
        "follow_ups": strings(data.get("follow_ups"), 2),
    }


def all_text(data: Dict) -> str:
    return "\n".join([data.get("answer", ""), *data.get("findings", []), *data.get("next_steps", []),
                      data.get("draft", "")])


def to_markdown(data: Dict) -> str:
    """The answer as plain Markdown, for the conversation history."""
    parts = [data.get("answer", "")]
    if data.get("findings"):
        parts.append("What the data shows:\n" + "\n".join(f"- {f}" for f in data["findings"]))
    if data.get("next_steps"):
        parts.append("Suggested next steps:\n" + "\n".join(f"- {s}" for s in data["next_steps"]))
    if data.get("draft"):
        parts.append("Draft:\n" + data["draft"])
    return "\n\n".join(p for p in parts if p)
