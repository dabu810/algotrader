"""
Multi-Model Provider — Unified LLM Interface
=============================================
Supports Anthropic (Claude), OpenAI (GPT), Google (Gemini), and Mistral.
The application admin switches providers via .env or CLI flag.

Configuration (.env):
    LLM_PROVIDER=anthropic            # anthropic | openai | gemini | mistral
    LLM_MODEL=claude-opus-4-6         # optional model override (see DEFAULTS)

    ANTHROPIC_API_KEY=...
    OPENAI_API_KEY=...
    GOOGLE_API_KEY=...
    MISTRAL_API_KEY=...

Tool definitions: use canonical OpenAI-style format with "parameters" key.
Each provider converts to its native format internally.

Web-search special tools: declare tools named "web_search" and "web_fetch".
  - Anthropic: auto-converted to server-side tools (web_search_20260209 etc.)
  - OpenAI / Gemini / Mistral: executed locally via DuckDuckGo + httpx.
"""

import os
import json
import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional, Any

log = logging.getLogger(__name__)

# ── Default models per provider ────────────────────────────────────────────────

PROVIDER_DEFAULTS: dict[str, str] = {
    "anthropic": "claude-opus-4-6",
    "openai":    "gpt-4o",
    "gemini":    "gemini-2.0-flash",
    "mistral":   "mistral-large-latest",
}

PROVIDER_MODELS: dict[str, list[str]] = {
    "anthropic": [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "o1",
        "o1-mini",
    ],
    "gemini": [
        "gemini-2.5-pro-preview-03-25",
        "gemini-2.5-flash-preview-04-17",
        "gemini-2.0-flash",
        "gemini-2.0-flash-001",
    ],
    "mistral": [
        "mistral-large-latest",
        "mistral-medium-latest",
        "mistral-small-latest",
        "open-mixtral-8x22b",
    ],
}

SUPPORTED_PROVIDERS = list(PROVIDER_DEFAULTS.keys())

# Server-side tool names used by Anthropic
_ANTHROPIC_SERVER_TOOLS = {"web_search", "web_fetch"}


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    done: bool = True


# ── Local web search / fetch (for non-Anthropic providers) ────────────────────

def _web_search(query: str, max_results: int = 6) -> dict:
    """DuckDuckGo search — free, no API key required."""
    try:
        from duckduckgo_search import DDGS  # type: ignore
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url":   r.get("href", ""),
                    "body":  r.get("body", "")[:500],
                })
        return {"results": results, "query": query}
    except ImportError:
        return {"error": "duckduckgo-search not installed. Run: pip install duckduckgo-search"}
    except Exception as e:
        return {"error": str(e)}


def _web_fetch(url: str, max_chars: int = 6000) -> dict:
    """Fetch a URL and return plain-text content."""
    try:
        import httpx  # type: ignore
        headers = {"User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)"}
        resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        content = resp.text

        # Strip HTML tags
        content = re.sub(r"<style[^>]*>.*?</style>", " ", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<script[^>]*>.*?</script>", " ", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"\s+", " ", content).strip()

        return {"url": url, "content": content[:max_chars], "truncated": len(content) > max_chars}
    except ImportError:
        return {"error": "httpx not installed. Run: pip install httpx"}
    except Exception as e:
        return {"error": str(e), "url": url}


def execute_web_tool(name: str, tool_input: dict) -> dict:
    """Route web tool calls for non-Anthropic providers."""
    if name == "web_search":
        return _web_search(tool_input.get("query", ""))
    if name == "web_fetch":
        return _web_fetch(tool_input.get("url", ""))
    return {"error": f"Unknown web tool: {name}"}


# ── Tool format converters ─────────────────────────────────────────────────────

def _to_openai_tools(tools: list[dict]) -> list[dict]:
    """Convert canonical tools to OpenAI function-calling format."""
    result = []
    for t in tools:
        result.append({
            "type": "function",
            "function": {
                "name":        t["name"],
                "description": t.get("description", ""),
                "parameters":  t.get("parameters", {"type": "object", "properties": {}}),
            }
        })
    return result


def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
    """
    Convert canonical tools to Anthropic format.
    Tools named 'web_search' or 'web_fetch' become server-side tools.
    """
    result = []
    for t in tools:
        name = t["name"]
        if name == "web_search":
            result.append({"type": "web_search_20260209", "name": "web_search"})
        elif name == "web_fetch":
            result.append({"type": "web_fetch_20260209", "name": "web_fetch"})
        else:
            result.append({
                "name":         name,
                "description":  t.get("description", ""),
                "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
            })
    return result


def _to_gemini_tools(tools: list[dict]):
    """Convert canonical tools to Gemini FunctionDeclaration format."""
    try:
        from google.genai import types as gtypes  # type: ignore
    except ImportError:
        raise ImportError("google-genai not installed. Run: pip install google-genai")

    declarations = []
    for t in tools:
        if t["name"] in _ANTHROPIC_SERVER_TOOLS:
            # Web search handled separately via Google Search grounding
            continue
        params = t.get("parameters", {})
        declarations.append(
            gtypes.FunctionDeclaration(
                name=t["name"],
                description=t.get("description", ""),
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        k: gtypes.Schema(
                            type=_json_type_to_gemini(v.get("type", "string")),
                            description=v.get("description", ""),
                            enum=v.get("enum"),
                        )
                        for k, v in params.get("properties", {}).items()
                    },
                    required=params.get("required", []),
                )
            )
        )
    return gtypes.Tool(function_declarations=declarations) if declarations else None


def _json_type_to_gemini(json_type: str):
    try:
        from google.genai import types as gtypes  # type: ignore
        mapping = {
            "string":  gtypes.Type.STRING,
            "number":  gtypes.Type.NUMBER,
            "integer": gtypes.Type.INTEGER,
            "boolean": gtypes.Type.BOOLEAN,
            "array":   gtypes.Type.ARRAY,
            "object":  gtypes.Type.OBJECT,
        }
        return mapping.get(json_type, gtypes.Type.STRING)
    except ImportError:
        return "STRING"


# ── Base provider ──────────────────────────────────────────────────────────────

class BaseProvider(ABC):
    """Abstract base for all LLM providers."""

    def __init__(self, model: str, api_key: str, max_tokens: int = 8192):
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens

    @abstractmethod
    def _start(self, system: str, tools: list[dict]) -> None:
        """Initialize internal conversation state."""

    @abstractmethod
    def _send_user(self, content: str) -> LLMResponse:
        """Send a user message; return response."""

    @abstractmethod
    def _send_tool_results(self, results: list[dict]) -> LLMResponse:
        """Send tool results; return next response."""

    def run(
        self,
        system: str,
        user_message: str,
        tools: list[dict],
        execute_fn: Callable[[ToolCall], dict],
        on_tool_call: Optional[Callable[[ToolCall], None]] = None,
    ) -> str:
        """
        Run a full agentic loop:
        1. Start conversation
        2. Send user message
        3. Execute any tool calls
        4. Repeat until model is done
        Returns the final text response.
        """
        self._start(system, tools)
        response = self._send_user(user_message)

        while not response.done:
            results = []
            for tc in response.tool_calls:
                if on_tool_call:
                    on_tool_call(tc)
                result = execute_fn(tc)
                results.append({
                    "tool_use_id": tc.id,
                    "name":        tc.name,
                    "content":     json.dumps(result, ensure_ascii=False),
                })
            response = self._send_tool_results(results)

        return response.text


# ── Anthropic provider ─────────────────────────────────────────────────────────

class AnthropicProvider(BaseProvider):
    """
    Claude (Anthropic) provider with adaptive thinking.
    Handles server-side web_search / web_fetch tools and pause_turn internally.
    """

    MAX_CONTINUATIONS = 8

    def _start(self, system: str, tools: list[dict]) -> None:
        import anthropic as _anthropic  # type: ignore
        self._client  = _anthropic.Anthropic(api_key=self.api_key)
        self._system  = system
        self._tools   = _to_anthropic_tools(tools)
        self._msgs: list[dict] = []

    def _send_user(self, content: str) -> LLMResponse:
        self._msgs.append({"role": "user", "content": content})
        return self._complete_loop()

    def _send_tool_results(self, results: list[dict]) -> LLMResponse:
        tool_results = [
            {"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": r["content"]}
            for r in results
        ]
        self._msgs.append({"role": "user", "content": tool_results})
        return self._complete_loop()

    def _complete_loop(self) -> LLMResponse:
        """Inner loop: handles pause_turn (server-side tool continuation)."""
        for _ in range(self.MAX_CONTINUATIONS):
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                thinking={"type": "adaptive"},
                system=self._system,
                tools=self._tools,
                messages=self._msgs,
            )
            self._msgs.append({"role": "assistant", "content": resp.content})

            text = " ".join(b.text for b in resp.content if b.type == "text")

            if resp.stop_reason == "end_turn":
                return LLMResponse(text=text, done=True)

            if resp.stop_reason == "pause_turn":
                # Server-side web tool hit iteration cap — re-send to continue
                self._msgs.append({"role": "user", "content": []})
                continue

            if resp.stop_reason == "tool_use":
                custom = [b for b in resp.content
                          if b.type == "tool_use" and b.name not in _ANTHROPIC_SERVER_TOOLS]
                if custom:
                    calls = [ToolCall(id=b.id, name=b.name, input=dict(b.input)) for b in custom]
                    return LLMResponse(text=text, tool_calls=calls, done=False)
                # All were server-side — shouldn't happen, but loop once more
                continue

        # Exceeded max continuations — return whatever text we have
        return LLMResponse(text="[Analysis exceeded max iterations]", done=True)


# ── OpenAI provider ────────────────────────────────────────────────────────────

class OpenAIProvider(BaseProvider):
    """GPT (OpenAI) provider with function calling."""

    def _start(self, system: str, tools: list[dict]) -> None:
        from openai import OpenAI  # type: ignore
        self._client = OpenAI(api_key=self.api_key)
        self._system = system
        self._tools  = _to_openai_tools(tools)
        self._msgs: list[dict] = [{"role": "system", "content": system}]

    def _send_user(self, content: str) -> LLMResponse:
        self._msgs.append({"role": "user", "content": content})
        return self._call()

    def _send_tool_results(self, results: list[dict]) -> LLMResponse:
        for r in results:
            self._msgs.append({
                "role":         "tool",
                "tool_call_id": r["tool_use_id"],
                "content":      r["content"],
            })
        return self._call()

    def _call(self) -> LLMResponse:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=self._msgs,
            max_tokens=self.max_tokens,
        )
        if self._tools:
            kwargs["tools"] = self._tools
            kwargs["tool_choice"] = "auto"

        resp = self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        # Append assistant message to history
        self._msgs.append(msg.model_dump(exclude_unset=True))

        if msg.tool_calls:
            calls = [
                ToolCall(id=tc.id, name=tc.function.name, input=json.loads(tc.function.arguments or "{}"))
                for tc in msg.tool_calls
            ]
            return LLMResponse(text=msg.content or "", tool_calls=calls, done=False)

        return LLMResponse(text=msg.content or "", done=True)


# ── Gemini provider ────────────────────────────────────────────────────────────

class GeminiProvider(BaseProvider):
    """Google Gemini provider with function calling."""

    def _start(self, system: str, tools: list[dict]) -> None:
        from google import genai as _genai      # type: ignore
        from google.genai import types as gtypes  # type: ignore
        self._genai  = _genai
        self._gtypes = gtypes
        self._client = _genai.Client(api_key=self.api_key)
        self._system = system
        self._gemini_tool = _to_gemini_tools(tools)
        self._history: list = []   # list of Content objects

    def _send_user(self, content: str) -> LLMResponse:
        gtypes = self._gtypes
        self._history.append(gtypes.Content(role="user", parts=[gtypes.Part(text=content)]))
        return self._call()

    def _send_tool_results(self, results: list[dict]) -> LLMResponse:
        gtypes = self._gtypes
        parts = [
            gtypes.Part(
                function_response=gtypes.FunctionResponse(
                    name=r["name"],
                    response={"result": r["content"]},
                )
            )
            for r in results
        ]
        self._history.append(gtypes.Content(role="user", parts=parts))
        return self._call()

    def _call(self) -> LLMResponse:
        gtypes = self._gtypes
        config = gtypes.GenerateContentConfig(
            system_instruction=self._system,
            tools=[self._gemini_tool] if self._gemini_tool else [],
            max_output_tokens=self.max_tokens,
        )
        resp = self._client.models.generate_content(
            model=self.model,
            contents=self._history,
            config=config,
        )
        candidate = resp.candidates[0]
        self._history.append(candidate.content)

        text_parts = [p.text for p in candidate.content.parts if hasattr(p, "text") and p.text]
        text = "\n".join(text_parts)

        fn_calls = [p.function_call for p in candidate.content.parts
                    if hasattr(p, "function_call") and p.function_call]

        if fn_calls:
            calls = [ToolCall(id=fc.name, name=fc.name, input=dict(fc.args)) for fc in fn_calls]
            return LLMResponse(text=text, tool_calls=calls, done=False)

        return LLMResponse(text=text, done=True)


# ── Mistral provider ───────────────────────────────────────────────────────────

class MistralProvider(BaseProvider):
    """Mistral AI provider with function calling."""

    def _start(self, system: str, tools: list[dict]) -> None:
        from mistralai import Mistral  # type: ignore
        self._client = Mistral(api_key=self.api_key)
        self._system = system
        self._tools  = _to_openai_tools(tools)   # Mistral uses same format as OpenAI
        self._msgs: list[dict] = [{"role": "system", "content": system}]

    def _send_user(self, content: str) -> LLMResponse:
        self._msgs.append({"role": "user", "content": content})
        return self._call()

    def _send_tool_results(self, results: list[dict]) -> LLMResponse:
        for r in results:
            self._msgs.append({
                "role":         "tool",
                "tool_call_id": r["tool_use_id"],
                "name":         r["name"],
                "content":      r["content"],
            })
        return self._call()

    def _call(self) -> LLMResponse:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=self._msgs,
            max_tokens=self.max_tokens,
        )
        if self._tools:
            kwargs["tools"] = self._tools
            kwargs["tool_choice"] = "auto"

        resp = self._client.chat.complete(**kwargs)
        msg = resp.choices[0].message
        self._msgs.append({"role": "assistant", "content": msg.content, "tool_calls": msg.tool_calls})

        if msg.tool_calls:
            calls = [
                ToolCall(id=tc.id, name=tc.function.name, input=json.loads(tc.function.arguments or "{}"))
                for tc in msg.tool_calls
            ]
            return LLMResponse(text=msg.content or "", tool_calls=calls, done=False)

        return LLMResponse(text=msg.content or "", done=True)


# ── Factory ────────────────────────────────────────────────────────────────────

def get_provider(
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 8192,
) -> BaseProvider:
    """
    Build and return a configured provider.
    Falls back to env vars LLM_PROVIDER and LLM_MODEL if args are None.
    """
    name = (provider_name or os.environ.get("LLM_PROVIDER", "anthropic")).lower().strip()

    if name not in PROVIDER_DEFAULTS:
        raise ValueError(
            f"Unknown provider '{name}'. "
            f"Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )

    resolved_model = (
        model
        or os.environ.get("LLM_MODEL")
        or PROVIDER_DEFAULTS[name]
    )

    key_env = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai":    "OPENAI_API_KEY",
        "gemini":    "GOOGLE_API_KEY",
        "mistral":   "MISTRAL_API_KEY",
    }[name]

    api_key = os.environ.get(key_env, "").strip().strip('"').strip("'")
    if not api_key:
        raise EnvironmentError(
            f"API key not set. Add {key_env}=<your-key> to your .env file."
        )
    # Catch placeholder values that weren't replaced
    if api_key.startswith("<") or api_key in ("your-key", "sk-...", "..."):
        raise EnvironmentError(
            f"{key_env} contains a placeholder value. "
            f"Replace it with your real API key in .env."
        )

    cls_map: dict[str, type[BaseProvider]] = {
        "anthropic": AnthropicProvider,
        "openai":    OpenAIProvider,
        "gemini":    GeminiProvider,
        "mistral":   MistralProvider,
    }

    log.info(f"Using provider: {name} | model: {resolved_model}")
    return cls_map[name](model=resolved_model, api_key=api_key, max_tokens=max_tokens)


def provider_info() -> str:
    """Return a formatted string showing configured provider + model."""
    name  = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    model = os.environ.get("LLM_MODEL") or PROVIDER_DEFAULTS.get(name, "unknown")
    return f"{name} / {model}"
