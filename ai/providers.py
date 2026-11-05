"""Connects the assistant to a language model.

Three providers share one small interface (`stream` and `json`):
- Gemini (Google AI Studio API): used for the public demo, on the free tier.
- Claude (Anthropic API): optional, if a key is configured.
- Ollama: a local model on a laptop. No data leaves the computer in this mode.

Which one is used is set in Streamlit secrets or environment variables:
    AI_PROVIDER = "gemini" | "claude" | "ollama"   (optional; otherwise the first one configured)
    GEMINI_API_KEY, GEMINI_MODEL                   (model optional)
    ANTHROPIC_API_KEY, CLAUDE_MODEL                (model optional)
    OLLAMA_MODEL                                   (optional, default qwen2.5:3b)

Keys are read only from secrets or the environment. They are never shown on
screen, logged or included in error messages. If no provider works, the
assistant says so; it never shows a made-up answer.

The model never changes a request. It only reads the text it is given.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, Iterator, List, Optional

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
MAX_OUTPUT_TOKENS = 1500


class AIError(RuntimeError):
    """A provider failure, with a message that is safe to show to a visitor."""


def setting(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st
        value = st.secrets.get(name)
    except Exception:  # no secrets file
        value = None
    return str(value) if value else None


def _safe_error(exc: Exception, provider: str) -> AIError:
    text = f"{type(exc).__name__} {exc}".lower()
    if "429" in text or "quota" in text or "rate limit" in text or "resource_exhausted" in text:
        return AIError(f"The {provider} free quota is used up for the moment. Please try again in a minute; "
                       "everything else in the app still works.")
    if "401" in text or "403" in text or "api key" in text or "permission" in text or "unauthenticated" in text:
        return AIError(f"The {provider} key was not accepted, so the assistant is unavailable.")
    if "timeout" in text or "connect" in text:
        return AIError(f"Could not reach {provider}. Please try again shortly.")
    return AIError(f"{provider} could not answer this time. Please try again.")


class Provider:
    name = "AI"
    hosted = True

    def stream(self, system: str, messages: List[Dict[str, str]]) -> Iterator[str]:
        raise NotImplementedError

    def json(self, system: str, text: str, keys: List[str]) -> Dict[str, str]:
        raise NotImplementedError


def _schema(keys: List[str]) -> dict:
    return {"type": "object", "properties": {k: {"type": "string"} for k in keys},
            "required": keys, "additionalProperties": False}


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise AIError("The AI did not return the fields in the expected format.")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        raise AIError("The AI did not return the fields in the expected format.")
    return {str(k): "" if v is None else str(v) for k, v in data.items()}


class Gemini(Provider):
    name = "Google Gemini"

    def __init__(self, key: str, model: str):
        from google import genai
        from google.genai import types
        self.types = types
        self.client = genai.Client(api_key=key)
        self.model = model

    def _contents(self, messages):
        return [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages]

    def stream(self, system, messages):
        config = self.types.GenerateContentConfig(system_instruction=system, temperature=0.2,
                                                  max_output_tokens=MAX_OUTPUT_TOKENS)
        try:
            for chunk in self.client.models.generate_content_stream(model=self.model,
                                                                    contents=self._contents(messages), config=config):
                if chunk.text:
                    yield chunk.text
        except AIError:
            raise
        except Exception as exc:
            raise _safe_error(exc, self.name) from None

    def json(self, system, text, keys):
        config = self.types.GenerateContentConfig(system_instruction=system, temperature=0,
                                                  max_output_tokens=MAX_OUTPUT_TOKENS,
                                                  response_mime_type="application/json",
                                                  response_json_schema=_schema(keys))
        try:
            reply = self.client.models.generate_content(model=self.model, contents=text, config=config)
        except Exception as exc:
            raise _safe_error(exc, self.name) from None
        return _parse_json(reply.text)


class Claude(Provider):
    name = "Claude"

    def __init__(self, key: str, model: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=key)
        self.model = model

    def _options(self, extra=None) -> dict:
        body = {"output_config": {"effort": "low", **(extra or {})}, "fallbacks": "default"}
        return {"extra_headers": {"anthropic-beta": "server-side-fallback-2026-07-01"}, "extra_body": body}

    def stream(self, system, messages):
        try:
            with self.client.messages.stream(model=self.model, max_tokens=MAX_OUTPUT_TOKENS, system=system,
                                             messages=messages, **self._options()) as s:
                yield from s.text_stream
                if s.get_final_message().stop_reason == "refusal":
                    yield "\n\nThe assistant could not answer this question."
        except Exception as exc:
            raise _safe_error(exc, self.name) from None

    def json(self, system, text, keys):
        try:
            reply = self.client.messages.create(
                model=self.model, max_tokens=MAX_OUTPUT_TOKENS, system=system,
                messages=[{"role": "user", "content": text}],
                **self._options({"format": {"type": "json_schema", "schema": _schema(keys)}}))
        except Exception as exc:
            raise _safe_error(exc, self.name) from None
        return _parse_json(next((b.text for b in reply.content if b.type == "text"), ""))


class Ollama(Provider):
    name = "Ollama (local)"
    hosted = False

    def __init__(self, client, model: str):
        self.client, self.model = client, model

    def stream(self, system, messages):
        try:
            chunks = self.client.chat(model=self.model, messages=[{"role": "system", "content": system}] + messages,
                                      stream=True, options={"temperature": 0.2, "num_ctx": 8192,
                                                            "num_predict": MAX_OUTPUT_TOKENS})
            for chunk in chunks:
                yield chunk["message"]["content"]
        except Exception as exc:
            raise _safe_error(exc, self.name) from None

    def json(self, system, text, keys):
        try:
            reply = self.client.chat(model=self.model, format="json", options={"temperature": 0},
                                     messages=[{"role": "system", "content": system},
                                               {"role": "user", "content": text}])
        except Exception as exc:
            raise _safe_error(exc, self.name) from None
        content = reply["message"]["content"] if isinstance(reply, dict) else reply.message.content
        return _parse_json(content)


def _try_gemini() -> Optional[Provider]:
    key = setting("GEMINI_API_KEY")
    if not key:
        return None
    try:
        return Gemini(key, setting("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL)
    except ImportError:
        return None


def _try_claude() -> Optional[Provider]:
    key = setting("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        return Claude(key, setting("CLAUDE_MODEL") or DEFAULT_CLAUDE_MODEL)
    except ImportError:
        return None


def _try_ollama() -> Optional[Provider]:
    try:
        import ollama
        listing = ollama.list()
        items = listing.models if hasattr(listing, "models") else listing.get("models", [])
        names = [getattr(m, "model", None) or m.get("name") for m in items]
    except Exception:  # Ollama not installed or not running
        return None
    if not names:
        return None
    wanted = setting("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL
    return Ollama(ollama, wanted if wanted in names else names[0])


def connect() -> Optional[Provider]:
    """The provider to use, or None when none is configured or reachable."""
    order = {"gemini": _try_gemini, "claude": _try_claude, "ollama": _try_ollama}
    chosen = (setting("AI_PROVIDER") or "").strip().lower()
    if chosen in order:
        return order[chosen]()
    for attempt in (_try_gemini, _try_claude, _try_ollama):
        provider = attempt()
        if provider:
            return provider
    return None
