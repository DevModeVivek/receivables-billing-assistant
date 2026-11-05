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
import logging
import os
import re
import time
from typing import Dict, Iterator, List, Optional

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"  # stable; set GEMINI_MODEL = "gemini-3.8-flash" for the larger model
DEFAULT_GEMINI_BACKUP = "gemini-3.8-flash"     # tried on the last attempt if the main model keeps failing
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
MAX_OUTPUT_TOKENS = 1500
GEMINI_MAX_OUTPUT_TOKENS = 4096  # Gemini counts its internal reasoning against this limit
RETRY_DELAYS = (1.5, 4.0)  # seconds to wait before the second and third attempts


LOG = logging.getLogger("billing_insights.ai")


def _log_failure(exc: Exception, provider: str, model: str) -> None:
    """Record why a call failed, for the app owner's logs. Only the error type and status code, never the message,
    which could contain a key."""
    LOG.warning("Assistant call failed: provider=%s model=%s error=%s code=%s", provider, model,
                type(exc).__name__, getattr(exc, "code", None) or getattr(exc, "status_code", None))


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
    """A plain message for the visitor. It never includes the provider's raw error, which could contain a key."""
    text = f"{type(exc).__name__} {exc}".lower()
    if "429" in text or "quota" in text or "rate limit" in text or "resource_exhausted" in text:
        return AIError("The assistant is busy right now. Please try again in a minute.")
    if "401" in text or "403" in text or "api key" in text or "permission" in text or "unauthenticated" in text:
        return AIError("The assistant is unavailable at the moment.")
    if "timeout" in text or "connect" in text:
        return AIError("Could not reach the assistant. Please try again shortly.")
    return AIError("The assistant could not answer this time. Please try again.")


class Provider:
    name = "AI"
    hosted = True
    model = ""

    def candidates(self) -> List[str]:
        """Models to use, main model first."""
        return [self.model]

    def stream(self, system: str, messages: List[Dict[str, str]], model: Optional[str] = None) -> Iterator[str]:
        raise NotImplementedError

    def structured(self, system: str, messages: List[Dict[str, str]], schema: dict,
                   model: Optional[str] = None) -> dict:
        """A reply that follows `schema` (a JSON Schema object), parsed into a dict."""
        raise NotImplementedError

    def json(self, system: str, text: str, keys: List[str], model: Optional[str] = None) -> Dict[str, str]:
        data = self.structured(system, [{"role": "user", "content": text}], _schema(keys), model)
        return {str(k): "" if v is None else str(v) for k, v in data.items()}


def _schema(keys: List[str]) -> dict:
    return {"type": "object", "properties": {k: {"type": "string"} for k in keys},
            "required": keys, "additionalProperties": False}


def _without(schema, key: str):
    """A copy of a JSON Schema with one keyword removed everywhere."""
    if isinstance(schema, dict):
        return {k: _without(v, key) for k, v in schema.items() if k != key}
    if isinstance(schema, list):
        return [_without(v, key) for v in schema]
    return schema


def _parse_obj(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise AIError("The AI did not return the fields in the expected format.")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        raise AIError("The AI did not return the fields in the expected format.")
    if not isinstance(data, dict):
        raise AIError("The AI did not return the fields in the expected format.")
    return data


class Gemini(Provider):
    name = "Google Gemini"

    def __init__(self, key: str, model: str, backup: Optional[str] = None):
        from google import genai
        from google.genai import types
        self.types = types
        self.client = genai.Client(api_key=key)
        self.model = model
        self.backup = backup if backup and backup != model else None

    def candidates(self):
        return [self.model] + ([self.backup] if self.backup else [])

    def _contents(self, messages):
        return [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages]

    def _call(self, model, messages, config):
        try:
            reply = self.client.models.generate_content(model=model or self.model,
                                                        contents=self._contents(messages), config=config)
            text = reply.text or ""
        except Exception as exc:
            _log_failure(exc, self.name, model or self.model)
            raise _safe_error(exc, self.name) from None
        if not text.strip():
            reason = getattr((reply.candidates or [None])[0], "finish_reason", None)
            LOG.warning("Assistant returned no text: model=%s finish_reason=%s", model or self.model, reason)
            raise AIError("The assistant returned an empty answer.")
        return text

    def stream(self, system, messages, model=None):
        # One complete request: the app shows only finished answers, and a single response cannot break off.
        config = self.types.GenerateContentConfig(system_instruction=system, temperature=0.2,
                                                  max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS)
        yield self._call(model, messages, config)

    def structured(self, system, messages, schema, model=None):
        config = self.types.GenerateContentConfig(system_instruction=system, temperature=0,
                                                  max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
                                                  response_mime_type="application/json",
                                                  response_json_schema=_without(schema, "additionalProperties"))
        return _parse_obj(self._call(model, messages, config))


class Claude(Provider):
    name = "Claude"

    def __init__(self, key: str, model: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=key)
        self.model = model

    def _options(self, extra=None) -> dict:
        body = {"output_config": {"effort": "low", **(extra or {})}, "fallbacks": "default"}
        return {"extra_headers": {"anthropic-beta": "server-side-fallback-2026-07-01"}, "extra_body": body}

    def stream(self, system, messages, model=None):
        try:
            with self.client.messages.stream(model=model or self.model, max_tokens=MAX_OUTPUT_TOKENS, system=system,
                                             messages=messages, **self._options()) as s:
                yield from s.text_stream
                if s.get_final_message().stop_reason == "refusal":
                    yield "\n\nThe assistant could not answer this question."
        except Exception as exc:
            _log_failure(exc, self.name, model or self.model)
            raise _safe_error(exc, self.name) from None

    def structured(self, system, messages, schema, model=None):
        try:
            reply = self.client.messages.create(
                model=model or self.model, max_tokens=MAX_OUTPUT_TOKENS, system=system, messages=messages,
                **self._options({"format": {"type": "json_schema", "schema": schema}}))
        except Exception as exc:
            _log_failure(exc, self.name, model or self.model)
            raise _safe_error(exc, self.name) from None
        return _parse_obj(next((b.text for b in reply.content if b.type == "text"), ""))


class Ollama(Provider):
    name = "Ollama (local)"
    hosted = False

    def __init__(self, client, model: str):
        self.client, self.model = client, model

    def stream(self, system, messages, model=None):
        try:
            chunks = self.client.chat(model=model or self.model,
                                      messages=[{"role": "system", "content": system}] + messages,
                                      stream=True, options={"temperature": 0.2, "num_ctx": 8192,
                                                            "num_predict": MAX_OUTPUT_TOKENS})
            for chunk in chunks:
                yield chunk["message"]["content"]
        except Exception as exc:
            raise _safe_error(exc, self.name) from None

    def structured(self, system, messages, schema, model=None):
        try:
            reply = self.client.chat(model=model or self.model, format=schema,
                                     options={"temperature": 0, "num_ctx": 8192},
                                     messages=[{"role": "system", "content": system}] + messages)
        except Exception as exc:
            raise _safe_error(exc, self.name) from None
        content = reply["message"]["content"] if isinstance(reply, dict) else reply.message.content
        return _parse_obj(content)


def _try_gemini() -> Optional[Provider]:
    key = setting("GEMINI_API_KEY")
    if not key:
        return None
    try:
        return Gemini(key, setting("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL,
                      setting("GEMINI_BACKUP_MODEL") or DEFAULT_GEMINI_BACKUP)
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


def _with_retries(provider: Provider, call):
    """Run `call(model)` up to three times. Brief overloads and dropped connections are common on free tiers, so a
    failure is retried quietly; the visitor sees nothing until a complete answer exists. If the main model is out
    of quota, or still failing on the last try, the backup model is used. A key problem is not retried."""
    models = provider.candidates() if hasattr(provider, "candidates") else [None]
    main, backup = models[0], (models[1] if len(models) > 1 else models[0])
    plan = [main, main, backup]
    last: Optional[AIError] = None
    for attempt in range(len(plan)):
        if attempt:
            time.sleep(RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)])
        try:
            return call(plan[attempt])
        except AIError as err:
            last = err
            if "unavailable" in str(err):
                break
            if "busy" in str(err):
                plan[attempt + 1:] = [backup] * (len(plan) - attempt - 1)
    raise last or AIError("The assistant could not answer this time.")


def answer(provider: Provider, system: str, messages: List[Dict[str, str]]) -> str:
    """Plain answer text, or AIError if every attempt failed or came back empty."""
    def once(model):
        text = "".join(provider.stream(system, messages, model))
        if not text.strip():
            raise AIError("The assistant returned an empty answer.")
        return text
    return _with_retries(provider, once)


def structured(provider: Provider, system: str, messages: List[Dict[str, str]], schema: dict) -> dict:
    """A reply that follows `schema`, with the same quiet retries."""
    return _with_retries(provider, lambda model: provider.structured(system, messages, schema, model))


def fields(provider: Provider, system: str, text: str, keys: List[str]) -> Dict[str, str]:
    """Field values read from text, with the same quiet retries."""
    return _with_retries(provider, lambda model: provider.json(system, text, keys, model) if model
                         else provider.json(system, text, keys))
