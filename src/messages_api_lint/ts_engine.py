"""A best-effort pass over TypeScript and JavaScript. Regexes and a bracket matcher, not a parser.

Findings carry engine="regex". It sees object literals written at the call site, or assigned to
a `const` in the same file; spreads, imports and helper functions are out of reach.
"""

from __future__ import annotations

import re

from . import rules
from .catalog import MODEL_ID_RE, SAMPLING_PARAMS
from .rules import Finding

ENGINE = "regex"
CALL_RE = re.compile(r"\.messages\s*\.\s*(create|stream|parse|countTokens)\s*(?:<[^>()]*>)?\s*\(")
RELEVANCE_RE = re.compile(r"@anthropic-ai/|[\"'`]claude-|\banthropic\b", re.IGNORECASE)
STRING_RE = re.compile(r"""'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`""")
KEY_RE = re.compile(r"""\s*(?:(['"])(?P<q>[\w.-]+)\1|(?P<b>[A-Za-z_$][\w$]*))\s*(?P<c>:)?""")
RESPONSE_ASSIGN_RE = re.compile(
    r"\b(?:const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*(?:await\s+)?[\w.]*\.messages\s*\.\s*"
    r"(?:create|parse)\s*(?:<[^>()]*>)?\s*\(|"
    r"\b(?:const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*(?:await\s+)?[\w.]*\.finalMessage\s*\("
)
OPENERS = {"(": ")", "[": "]", "{": "}"}


def strip_comments(source: str) -> str:
    """Blank out comments, keeping offsets and newlines. Regex literals are not understood."""
    out = list(source)
    index = 0
    quote: str | None = None
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote or (char == "\n" and quote != "`"):
                quote = None
        elif char in "'\"`":
            quote = char
        elif source.startswith("//", index):
            end = source.find("\n", index)
            end = len(source) if end == -1 else end
            out[index:end] = " " * (end - index)
            index = end
            continue
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = len(source) if end == -1 else end + 2
            out[index:end] = ["\n" if c == "\n" else " " for c in source[index:end]]
            index = end
            continue
        index += 1
    return "".join(out)


def match_bracket(text: str, start: int) -> int:
    """Index of the bracket closing the one at `start`, or -1. Strings are skipped."""
    closing: list[str] = []
    index = start
    while index < len(text):
        char = text[index]
        if char in "'\"`":
            match = STRING_RE.match(text, index)
            index = match.end() if match else index + 1  # a stray apostrophe, say in JSX text
            continue
        if char in OPENERS:
            closing.append(OPENERS[char])
        elif closing and char == closing[-1]:
            closing.pop()
            if not closing:
                return index
        index += 1
    return -1


def split_top_level(inner: str) -> list[tuple[int, str]]:
    """Split on top-level commas; returns (offset, chunk) pairs."""
    chunks: list[tuple[int, str]] = []
    start = index = 0
    while index < len(inner):
        char = inner[index]
        if char in "'\"`":
            match = STRING_RE.match(inner, index)
            index = match.end() if match else index + 1
            continue
        if char in OPENERS:
            end = match_bracket(inner, index)
            if end == -1:
                break
            index = end + 1
            continue
        if char == ",":
            chunks.append((start, inner[start:index]))
            start = index + 1
        index += 1
    if inner[start:].strip():
        chunks.append((start, inner[start:]))
    return chunks


def object_fields(text: str, start: int) -> dict[str, tuple[int, str]]:
    """Top-level `key: value` pairs of the object literal at text[start], with value offsets."""
    end = match_bracket(text, start)
    if end == -1:
        return {}
    fields: dict[str, tuple[int, str]] = {}
    for offset, chunk in split_top_level(text[start + 1 : end]):
        match = KEY_RE.match(chunk)
        if not match or chunk.lstrip().startswith("..."):
            continue
        key = match.group("q") or match.group("b")
        if match.group("c"):
            value = chunk[match.end() :]
            lead = len(value) - len(value.lstrip())
            fields[key] = (start + 1 + offset + match.end() + lead, value.strip())
        elif chunk.strip() == key:  # shorthand: { tool_choice }
            fields[key] = (start + 1 + offset, key)
    return fields


def string_value(value: str) -> str | None:
    match = STRING_RE.fullmatch(value.strip())
    return match.group(0)[1:-1] if match else None


class TypeScriptLinter:
    def __init__(self, path: str, source: str, assume_model: str | None = None) -> None:
        self.path = path
        self.text = strip_comments(source)
        self.assume_model = assume_model
        self.findings: list[Finding] = []

    def line_of(self, offset: int) -> int:
        return self.text.count("\n", 0, offset) + 1

    def report(self, rule_id: str, offset: int, verdict: tuple[str, str] | None) -> None:
        if verdict:
            self.findings.append(
                Finding(rule_id, verdict[0], self.path, self.line_of(offset), verdict[1], ENGINE)
            )

    def run(self) -> list[Finding]:
        for match in STRING_RE.finditer(self.text):
            value = match.group(0)[1:-1]
            for model in MODEL_ID_RE.finditer(value):
                self.report("MA007", match.start(), rules.model_id(model.group(0)))
            self.report("MA008", match.start(), rules.tool_version(value))
        if not RELEVANCE_RE.search(self.text):
            return self.findings
        for match in CALL_RE.finditer(self.text):
            self.check_call(match.end() - 1, match.group(1))
        self.check_responses()
        return self.findings

    def _const_value(self, name: str) -> str | None:
        """The right-hand side of `const name = ...` in this file, if it is simple to find."""
        if not re.fullmatch(r"[A-Za-z_$][\w$]*", name):
            return None
        match = re.search(rf"\b(?:const|let|var)\s+{re.escape(name)}\b[^=\n]*=\s*", self.text)
        if not match:
            return None
        start = match.end()
        if start < len(self.text) and self.text[start] in OPENERS:
            end = match_bracket(self.text, start)
            return self.text[start : end + 1] if end != -1 else None
        end = self.text.find("\n", start)
        return self.text[start : end if end != -1 else len(self.text)].rstrip("; ")

    def _resolve(self, value: str) -> str:
        resolved = self._const_value(value.strip())
        return resolved if resolved is not None else value

    def _object_start(self, value: str, offset: int) -> tuple[str, int] | None:
        """Find the object a value denotes; returns (text, start), following one `const`."""
        if value.startswith("{"):
            return self.text, offset
        match = re.search(
            rf"\b(?:const|let|var)\s+{re.escape(value)}\b[^=\n]*=\s*(?=\{{)", self.text
        )
        return (self.text, match.end()) if match else None

    def check_call(self, paren: int, method: str) -> None:
        end = match_bracket(self.text, paren)
        if end == -1:
            return
        args_start = paren + 1
        while args_start < end and self.text[args_start].isspace():
            args_start += 1
        first = split_top_level(self.text[args_start:end])
        if not first:
            return
        located = self._object_start(first[0][1].strip(), args_start)
        if not located:
            return
        fields = object_fields(*located)
        call_offset = args_start

        model = None
        if "model" in fields:
            model = string_value(self._resolve(fields["model"][1]))
            if model is not None and "claude" not in model:
                return
        model = model or self.assume_model

        if "thinking" in fields:
            offset, value = fields["thinking"]
            if re.search(r"\bbudget_?[tT]okens\b", self._resolve(value)):
                self.report("MA001", offset, rules.budget_tokens(model))

        for param in SAMPLING_PARAMS:
            if param in fields:
                offset, value = fields[param]
                try:
                    number: float | None = float(self._resolve(value))
                except ValueError:
                    number = None
                self.report("MA002", offset, rules.sampling(model, param, number))
        if "temperature" in fields and "top_p" in fields:
            self.report("MA003", call_offset, rules.temperature_and_top_p(model))

        if "messages" in fields:
            self._check_prefill(*fields["messages"], model)

        if "tool_choice" in fields:
            offset, value = fields["tool_choice"]
            kind = re.search(r"""\btype\s*:\s*['"`](any|tool)['"`]""", self._resolve(value))
            if kind:
                self.report("MA005", offset, rules.forced_tool_choice(model, kind.group(1)))

        if "output_format" in fields and method != "parse":
            self.report("MA006", fields["output_format"][0], rules.output_format())

    def _check_prefill(self, offset: int, value: str, model: str | None) -> None:
        text = self._resolve(value).strip()
        if not text.startswith("[") or not text.endswith("]"):
            return
        elements = split_top_level(text[1:-1])
        if not elements:
            return
        last_offset, chunk = elements[-1]
        last = chunk.strip()
        at = offset + 1 + last_offset + len(chunk) - len(chunk.lstrip())
        if last.startswith("{") and re.search(r"""\brole\s*:\s*['"`]assistant['"`]""", last):
            content = re.search(r"""\bcontent\s*:\s*(['"`\[])""", last)
            if content:  # echoing `response.content` is a resume, not a prefill
                # A `const` holds the text elsewhere; then the array's own line is the best we have.
                self.report("MA004", at if text == value else offset, rules.prefill(model))

    def check_responses(self) -> None:
        for match in RESPONSE_ASSIGN_RE.finditer(self.text):
            name = match.group(1) or match.group(2)
            rest = self.text[match.end() :]
            if not re.search(rf"\b{re.escape(name)}\.content\b", rest):
                continue
            if re.search(rf"\b{re.escape(name)}\.stop_reason\b", rest):
                compared = re.findall(
                    rf"\b{re.escape(name)}\.stop_reason\s*[!=]==?\s*['\"`](\w+)", rest
                )
                if compared and "refusal" not in compared:
                    self.report("MA010", match.start(), rules.no_refusal_branch(name))
                continue
            # A bare use (return, argument) means someone else may check it.
            if re.search(rf"\b{re.escape(name)}\b(?!\s*\.|\s*\?\.|\s*:|\s*=[^=])", rest):
                continue
            self.report("MA009", match.start(), rules.missing_stop_reason(name))
