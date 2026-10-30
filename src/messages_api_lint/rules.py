"""Decisions shared by both engines: given what was found, which severity and which words."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .catalog import (
    CURRENT_WEB_TOOLS,
    DATED_ACTIVE,
    DEFAULT_SAMPLING,
    DEPRECATED,
    LEGACY_TOOL_NAMES,
    MODEL_FACTS,
    RETIRED,
    RULES,
    RULES_WRITTEN,
    TOOL_VERSION_RE,
    Support,
    canonical_model,
)


@dataclass
class Finding:
    rule_id: str
    severity: str
    path: str
    line: int
    message: str
    engine: str  # "ast" or "regex"

    def to_dict(self) -> dict[str, Any]:
        rule = RULES[self.rule_id]
        return {
            "rule": self.rule_id,
            "severity": self.severity,
            "title": rule.title,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "engine": self.engine,
            "citations": [str(c) for c in rule.citations],
        }


Verdict = tuple[str, str]  # (severity, message)


def _support(model: str | None, attribute: str) -> Support:
    alias = canonical_model(model)
    return getattr(MODEL_FACTS[alias], attribute) if alias else Support.UNKNOWN


def _named(model: str | None) -> str:
    return model if model else "an unresolved model"


def budget_tokens(model: str | None) -> Verdict:
    support = _support(model, "budget_tokens")
    if support is Support.REJECTED:
        return "error", (
            f"`budget_tokens` returns a 400 on {model}; use `thinking={{'type': 'adaptive'}}` and "
            "`output_config.effort`"
        )
    if support is Support.DEPRECATED:
        return "warning", f"`budget_tokens` is deprecated on {model}; move to adaptive thinking"
    if support is Support.ACCEPTED:
        return "info", f"{model} accepts `budget_tokens`, but its successors reject it"
    return "warning", (
        f"`budget_tokens` on {_named(model)}; it returns a 400 on Opus 4.7 and later, "
        "Sonnet 5 and later, and Haiku 5.5"
    )


def sampling(model: str | None, param: str, value: Any) -> Verdict:
    support = _support(model, "sampling")
    is_default = param in DEFAULT_SAMPLING and value == DEFAULT_SAMPLING[param]
    api_note = "API version 2026-10-21 rejects it on every model"
    if support is Support.REJECTED and not is_default:
        shown = "" if value is None else f"={value!r}"
        return (
            "error",
            f"`{param}{shown}` returns a 400 on {model}; omit it and steer in the prompt",
        )
    if support is Support.REJECTED:
        return "warning", f"`{param}={value!r}` is the only accepted value on {model}; {api_note}"
    return "warning", f"`{param}` on {_named(model)}; {api_note}"


def temperature_and_top_p(model: str | None) -> Verdict:
    if model and model.startswith(("claude-3", "claude-2")):
        return "info", f"{model} accepts both, but every Claude 4+ model rejects the pair"
    if model is None:
        return "warning", "`temperature` and `top_p` together return a 400 on every Claude 4+ model"
    return "error", f"`temperature` and `top_p` together return a 400 on {model}"


def prefill(model: str | None) -> Verdict:
    support = _support(model, "prefill")
    if support is Support.REJECTED:
        return "error", (
            f"a final assistant turn returns a 400 on {model}; use `output_config.format` or a "
            "system prompt instruction"
        )
    if support is Support.ACCEPTED:
        return "info", f"{model} accepts prefill, but its successors reject it"
    return "warning", (
        f"a final assistant turn on {_named(model)}; prefill returns a 400 on Opus 4.6 and later, "
        "Sonnet 4.6 and later, and Haiku 5.5"
    )


def forced_tool_choice(model: str | None, kind: str) -> Verdict:
    support = _support(model, "forced_tool_choice")
    if support is Support.REJECTED:
        return "error", (
            f"`tool_choice` type {kind!r} returns a 400 on {model}; use `auto`, name the tool in "
            "the prompt, set `strict: true`, and check that a call was made"
        )
    if support is Support.ACCEPTED:
        return (
            "info",
            f"{model} accepts forced `tool_choice`, but Opus 5.5 and Sonnet 5.5 reject it",
        )
    return "warning", (
        f"`tool_choice` type {kind!r} on {_named(model)}; it returns a 400 on Opus 5.5, "
        "Sonnet 5.5, Fable 5.1 and Mythos 5.1"
    )


def output_format() -> Verdict:
    return "warning", "top-level `output_format` is deprecated; use `output_config.format`"


def model_id(value: str) -> Verdict | None:
    if value in RETIRED:
        replacement, when = RETIRED[value]
        return "error", f"{value} was retired on {when} and returns a 404; use {replacement}"
    if value in DEPRECATED:
        replacement, when = DEPRECATED[value]
        passed = (
            f"; that date precedes these rules ({RULES_WRITTEN}), so it may already be gone"
            if when < RULES_WRITTEN
            else ""
        )
        return "warning", f"{value} is listed as retiring on {when}{passed}; use {replacement}"
    if value in DATED_ACTIVE:
        return "info", f"dated snapshot {value}; the alias is {DATED_ACTIVE[value]}"
    if value[-8:].isdigit():
        return "warning", f"dated model ID {value} is not in the reference tables; check it exists"
    return None


def tool_version(value: str) -> Verdict | None:
    if value in LEGACY_TOOL_NAMES:
        return "warning", (
            f"{value} is a legacy tool version, not supported on Claude 4+; use "
            f"{LEGACY_TOOL_NAMES[value]} (`type` and `name` change together)"
        )
    match = TOOL_VERSION_RE.match(value)
    if match and int(match.group(2)) < CURRENT_WEB_TOOLS[match.group(1)]:
        current = f"{match.group(1)}_{CURRENT_WEB_TOOLS[match.group(1)]}"
        return "warning", f"{value} still works but has no dynamic filtering; {current} does"
    return None


def missing_stop_reason(name: str) -> Verdict:
    return "warning", (
        f"`{name}.content` is read but `{name}.stop_reason` never is; a `refusal` is an HTTP 200, "
        "and `max_tokens` means a cut-off reply"
    )


def no_refusal_branch(name: str) -> Verdict:
    return "info", f"`{name}.stop_reason` is compared, but never against 'refusal'"
