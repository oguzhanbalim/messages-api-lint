"""What the rules know, and where each fact came from.

The API changes. Everything in this file was transcribed on RULES_WRITTEN from the reference
named in RULES_SOURCE, so treat it as a dated snapshot rather than as the current truth.
`messages-api-lint --check-citations DIR` re-checks every cited section against a newer copy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

RULES_WRITTEN = "2026-10-30"
RULES_SOURCE = "claude-api skill bundled with Claude Code 2.1.309"
MIGRATION = "shared/model-migration.md"
MODELS = "shared/models.md"
API_VERSION = "shared/api-version-migration.md"
TOOL_USE = "shared/tool-use-concepts.md"
PY_README = "python/claude-api/README.md"


@dataclass(frozen=True)
class Citation:
    file: str
    section: str

    def __str__(self) -> str:
        return f"{self.file} § {self.section}"


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    citations: tuple[Citation, ...]


_RULES = (
    Rule(
        "MA001",
        "`budget_tokens` in a thinking config",
        (
            Citation(MIGRATION, "`thinking` - `budget_tokens` -> adaptive"),
            Citation(MIGRATION, "Breaking changes (will 400 on Opus 4.7)"),
            Citation(MIGRATION, "Breaking change 1: thinking can't be disabled"),
        ),
    ),
    Rule(
        "MA002",
        "sampling parameter on a model or API version that rejects it",
        (
            Citation(MIGRATION, "Sampling parameters - `temperature` / `top_p` / `top_k`"),
            Citation(MIGRATION, "Breaking change 2: non-default sampling parameters return a 400"),
            Citation(API_VERSION, "1. Sampling parameters are removed"),
        ),
    ),
    Rule(
        "MA003",
        "`temperature` and `top_p` sent together",
        (Citation(MIGRATION, "Additional Changes When Coming from 3.x / 4.0 / 4.1 -> 4.6"),),
    ),
    Rule(
        "MA004",
        "assistant prefill as the last message",
        (
            Citation(MIGRATION, "Migrating to the 4.6 family (Opus 4.6 and Sonnet 4.6)"),
            Citation(
                MIGRATION, "Prefill replacement - structured outputs via `output_config.format`"
            ),
            Citation(MIGRATION, "Breaking change 3: assistant prefill returns a 400"),
        ),
    ),
    Rule(
        "MA005",
        "forced `tool_choice`",
        (
            Citation(MIGRATION, "Breaking change 2: forced tool use is rejected"),
            Citation(MIGRATION, "Breaking change 1: forced tool use is rejected"),
        ),
    ),
    Rule(
        "MA006",
        "deprecated top-level `output_format`",
        (Citation(MIGRATION, "All models"), Citation(TOOL_USE, "Structured Outputs")),
    ),
    Rule(
        "MA007",
        "dated, deprecated or retired model ID",
        (
            Citation(MIGRATION, "Retired Model Replacements"),
            Citation(MIGRATION, "Deprecated Models (retiring soon)"),
            Citation(MODELS, "Retired Models (no longer available)"),
            Citation(MODELS, "Legacy Models (still active)"),
        ),
    ),
    Rule(
        "MA008",
        "old server or client tool version",
        (
            Citation(
                TOOL_USE,
                "Dynamic Filtering (Claude Opus 5.5 / Claude Opus 5 / Fable 5 / Opus 4.8 / "
                "Opus 4.7 / Opus 4.6 / Claude Sonnet 5.5 / Sonnet 5 / Sonnet 4.6)",
            ),
            Citation(MIGRATION, "Additional Changes When Coming from 3.x / 4.0 / 4.1 -> 4.6"),
        ),
    ),
    Rule(
        "MA009",
        "response content read without checking `stop_reason`",
        (
            Citation(PY_README, "Stop Reasons"),
            Citation(MIGRATION, "`refusal` stop reason - handle before reading content"),
        ),
    ),
    Rule(
        "MA010",
        "`stop_reason` branches never handle `refusal`",
        (
            Citation(MIGRATION, "Additional Changes When Coming from 3.x / 4.0 / 4.1 -> 4.6"),
            Citation(PY_README, "Stop Reasons"),
        ),
    ),
)
RULES: dict[str, Rule] = {rule.id: rule for rule in _RULES}


class Support(Enum):
    REJECTED = "rejected"  # documented 400
    DEPRECATED = "deprecated"  # still works, documented as deprecated
    ACCEPTED = "accepted"
    UNKNOWN = "unknown"  # the reference does not say


@dataclass(frozen=True)
class ModelFacts:
    budget_tokens: Support
    sampling: Support
    prefill: Support
    forced_tool_choice: Support


_R, _D, _A, _U = Support.REJECTED, Support.DEPRECATED, Support.ACCEPTED, Support.UNKNOWN
MODEL_FACTS: dict[str, ModelFacts] = {
    "claude-fable-5-1": ModelFacts(_R, _R, _R, _R),
    "claude-mythos-5-1": ModelFacts(_R, _R, _R, _R),
    "claude-fable-5": ModelFacts(_R, _R, _R, _A),
    "claude-mythos-5": ModelFacts(_R, _R, _R, _A),
    "claude-mythos-preview": ModelFacts(_R, _U, _R, _U),
    "claude-opus-5-5": ModelFacts(_R, _R, _R, _R),
    "claude-opus-5": ModelFacts(_R, _R, _R, _A),
    "claude-opus-4-8": ModelFacts(_R, _R, _R, _A),
    "claude-opus-4-7": ModelFacts(_R, _R, _R, _A),
    "claude-opus-4-6": ModelFacts(_D, _A, _R, _A),
    "claude-opus-4-5": ModelFacts(_A, _A, _A, _A),
    "claude-opus-4-1": ModelFacts(_A, _A, _A, _A),
    "claude-opus-4-0": ModelFacts(_A, _A, _A, _A),
    "claude-sonnet-5-5": ModelFacts(_R, _R, _R, _R),
    "claude-sonnet-5": ModelFacts(_R, _R, _R, _A),
    "claude-sonnet-4-6": ModelFacts(_D, _A, _R, _A),
    "claude-sonnet-4-5": ModelFacts(_A, _A, _A, _A),
    "claude-sonnet-4-0": ModelFacts(_A, _A, _A, _A),
    "claude-haiku-5-5": ModelFacts(_R, _R, _R, _A),
    "claude-haiku-4-5": ModelFacts(_A, _A, _A, _A),
}

# ID -> (replacement, retirement date), merged from the two tables in the reference.
RETIRED = {
    "claude-3-7-sonnet-20250219": ("claude-sonnet-5-5", "2026-02-19"),
    "claude-3-5-haiku-20241022": ("claude-haiku-5-5", "2026-02-19"),
    "claude-3-opus-20240229": ("claude-opus-4-8", "2026-01-05"),
    "claude-3-5-sonnet-20241022": ("claude-sonnet-5-5", "2025-10-28"),
    "claude-3-5-sonnet-20240620": ("claude-sonnet-5-5", "2025-10-28"),
    "claude-3-sonnet-20240229": ("claude-sonnet-5-5", "2025-07-21"),
    "claude-2.1": ("claude-sonnet-5-5", "2025-07-21"),
    "claude-2.0": ("claude-sonnet-5-5", "2025-07-21"),
}
# The two reference files disagree on some of these dates ("TBD" against a date), and every date
# below has passed as of RULES_WRITTEN without the model moving to the retired table. They stay
# warnings and the message says so; the linter cannot check them without calling the API.
DEPRECATED = {
    "claude-3-haiku-20240307": ("claude-haiku-5-5", "2026-04-19"),
    "claude-opus-4-20250514": ("claude-opus-5-5", "2026-06-15"),
    "claude-sonnet-4-20250514": ("claude-sonnet-5-5", "2026-06-15"),
    "claude-opus-4-1-20250805": ("claude-opus-5-5", "2026-08-05"),
}
DATED_ACTIVE = {
    "claude-opus-4-5-20251101": "claude-opus-4-5",
    "claude-sonnet-4-5-20250929": "claude-sonnet-4-5",
    "claude-haiku-4-5-20251001": "claude-haiku-4-5",
}
MODEL_ID_RE = re.compile(r"claude-(?:2\.[01]|[a-z0-9-]*?-\d{8}\b)")

CURRENT_WEB_TOOLS = {"web_search": 20260209, "web_fetch": 20260209}
TOOL_VERSION_RE = re.compile(r"^(web_search|web_fetch)_(\d{8})$")
LEGACY_TOOL_NAMES = {
    "text_editor_20250124": "text_editor_20250728",
    "str_replace_editor": "str_replace_based_edit_tool",
}
DEFAULT_SAMPLING = {"temperature": 1, "top_p": 0.99}
SAMPLING_PARAMS = ("temperature", "top_p", "top_k")


def canonical_model(model_id: str | None) -> str | None:
    """Reduce a model string to the alias used in MODEL_FACTS, or None if it is not one we know."""
    if not model_id:
        return None
    match = re.search(r"claude-[a-z0-9.-]+", model_id)
    if not match:
        return None
    name = re.sub(r"-\d{8}.*$", "", match.group(0))
    name = {"claude-opus-4": "claude-opus-4-0", "claude-sonnet-4": "claude-sonnet-4-0"}.get(
        name, name
    )
    return name if name in MODEL_FACTS else None
