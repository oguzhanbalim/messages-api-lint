"""Find stale API usage in Python through the AST. Nothing is imported or executed."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass, field

from . import rules
from .catalog import MODEL_ID_RE, SAMPLING_PARAMS
from .rules import Finding

ENDPOINTS = {"create", "stream", "parse", "count_tokens"}
RESPONSE_METHODS = {"create", "parse"}
SERIALISERS = {"model_dump", "model_dump_json", "to_dict", "to_json", "json", "dict"}
ENGINE = "ast"


def dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif not isinstance(node, ast.Call | ast.Await | ast.Subscript):
        return None
    return ".".join(reversed(parts))


def _endpoint(call: ast.Call) -> str | None:
    """The method name, when the call looks like `<something>.messages.<method>(...)`."""
    name = dotted(call.func)
    if not name:
        return None
    parts = name.split(".")
    if len(parts) >= 2 and parts[-2] == "messages" and parts[-1] in ENDPOINTS:
        return parts[-1]
    return None


@dataclass
class Scope:
    """Assignments visible in a function or module, last write wins."""

    node: ast.AST
    parent: Scope | None = None
    names: dict[str, ast.expr] = field(default_factory=dict)

    def lookup(self, name: str) -> ast.expr | None:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.names:
                return scope.names[name]
            scope = scope.parent
        return None

    def resolve(self, node: ast.expr | None) -> ast.expr | None:
        seen = 0
        while isinstance(node, ast.Name) and seen < 8:
            target = self.lookup(node.id)
            if target is None:
                return node
            node = target
            seen += 1
        return node


def own_nodes(scope_node: ast.AST) -> Iterator[ast.AST]:
    """Walk a scope without descending into nested functions or classes."""
    stack = list(ast.iter_child_nodes(scope_node))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            stack.extend(ast.iter_child_nodes(node))


def _dict_get(node: ast.Dict, key: str) -> ast.expr | None:
    for k, v in zip(node.keys, node.values, strict=True):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


def _const(node: ast.expr | None) -> object | None:
    return node.value if isinstance(node, ast.Constant) else None


class PythonLinter:
    def __init__(self, path: str, source: str, assume_model: str | None = None) -> None:
        self.path = path
        self.source = source
        self.assume_model = assume_model
        self.findings: list[Finding] = []
        self.claimed: set[int] = set()  # dicts already handled as part of a request

    def report(self, rule_id: str, line: int, verdict: tuple[str, str] | None) -> None:
        if verdict:
            self.findings.append(Finding(rule_id, verdict[0], self.path, line, verdict[1], ENGINE))

    def run(self) -> list[Finding]:
        tree = ast.parse(self.source, filename=self.path)
        self.relevant = self._mentions_the_api(tree)
        self.check_strings(tree)
        if self.relevant:
            self.visit_scope(tree, None)
            self.check_stray_budget_tokens(tree)
        return self.findings

    @staticmethod
    def _mentions_the_api(tree: ast.Module) -> bool:
        """Other SDKs also have `client.messages.create`; require evidence this one is ours."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = [alias.name for alias in node.names]
                module = getattr(node, "module", None) or ""
                if module.split(".")[0] == "anthropic" or any(
                    n.split(".")[0] == "anthropic" for n in names
                ):
                    return True
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "claude-" in node.value
            ):
                return True
        return False

    def check_strings(self, tree: ast.Module) -> None:
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Constant)
                or not isinstance(node.value, str)
                or id(node) in docstrings
            ):
                continue
            for match in MODEL_ID_RE.finditer(node.value):
                self.report("MA007", node.lineno, rules.model_id(match.group(0)))
            self.report("MA008", node.lineno, rules.tool_version(node.value))

    def visit_scope(self, scope_node: ast.AST, parent: Scope | None) -> None:
        scope = Scope(scope_node, parent)
        nodes = list(own_nodes(scope_node))
        nodes.sort(key=lambda n: (getattr(n, "lineno", 0), getattr(n, "col_offset", 0)))
        for node in nodes:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                if isinstance(node.targets[0], ast.Name):
                    scope.names[node.targets[0].id] = node.value
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.value is not None
            ):
                scope.names[node.target.id] = node.value

        for node in nodes:
            if isinstance(node, ast.Call):
                method = _endpoint(node)
                if method:
                    self.check_request(
                        self._kwargs_of_call(node, scope), node.lineno, scope, method
                    )
        for node in nodes:
            if (
                isinstance(node, ast.Dict)
                and id(node) not in self.claimed
                and _dict_get(node, "model") is not None
                and _dict_get(node, "messages") is not None
            ):
                pairs = self._kwargs_of_dict(node, scope)
                self.check_request(pairs, node.lineno, scope, "payload")

        self.check_responses(nodes, scope)
        for node in nodes:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                self.visit_scope(node, scope)

    def _kwargs_of_call(self, call: ast.Call, scope: Scope) -> dict[str, ast.expr]:
        kwargs: dict[str, ast.expr] = {}
        for keyword in call.keywords:
            if keyword.arg is not None:
                kwargs[keyword.arg] = keyword.value
                continue
            spread = scope.resolve(keyword.value)
            if isinstance(spread, ast.Dict):
                kwargs.update(self._kwargs_of_dict(spread, scope))
        return kwargs

    def _kwargs_of_dict(self, node: ast.Dict, scope: Scope) -> dict[str, ast.expr]:
        self.claimed.add(id(node))
        kwargs: dict[str, ast.expr] = {}
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                spread = scope.resolve(value)
                if isinstance(spread, ast.Dict):
                    kwargs.update(self._kwargs_of_dict(spread, scope))
            elif isinstance(key, ast.Constant) and isinstance(key.value, str):
                kwargs[key.value] = value
        return kwargs

    def check_request(
        self, kwargs: dict[str, ast.expr], line: int, scope: Scope, method: str
    ) -> None:
        model_value = _const(scope.resolve(kwargs.get("model")))
        model = model_value if isinstance(model_value, str) else self.assume_model
        if isinstance(model_value, str) and "claude" not in model_value:
            return

        # `extra_body` carries the same fields past the SDK's type checks.
        extra = scope.resolve(kwargs.get("extra_body"))
        if isinstance(extra, ast.Dict):
            for key, value in self._kwargs_of_dict(extra, scope).items():
                kwargs.setdefault(key, value)

        thinking = scope.resolve(kwargs.get("thinking"))
        if thinking is not None:
            for node in ast.walk(thinking):
                if self._is_budget_tokens(node):
                    self.claimed.add(id(node))
                    self.report("MA001", node.lineno, rules.budget_tokens(model))

        present = [p for p in SAMPLING_PARAMS if p in kwargs]
        for param in present:
            node = kwargs[param]
            value = _const(scope.resolve(node))
            self.report("MA002", node.lineno, rules.sampling(model, param, value))
        if "temperature" in kwargs and "top_p" in kwargs:
            self.report("MA003", line, rules.temperature_and_top_p(model))

        self._check_prefill(kwargs.get("messages"), scope, model)

        tool_choice = scope.resolve(kwargs.get("tool_choice"))
        if isinstance(tool_choice, ast.Dict):
            kind = _const(_dict_get(tool_choice, "type"))
            if kind in ("any", "tool"):
                self.report("MA005", tool_choice.lineno, rules.forced_tool_choice(model, kind))

        if "output_format" in kwargs and method != "parse":
            self.report("MA006", kwargs["output_format"].lineno, rules.output_format())

    @staticmethod
    def _is_budget_tokens(node: ast.AST) -> bool:
        if isinstance(node, ast.Dict):
            return _dict_get(node, "budget_tokens") is not None
        return isinstance(node, ast.Call) and any(
            k.arg in ("budget_tokens", "budgetTokens") for k in node.keywords
        )

    def check_stray_budget_tokens(self, tree: ast.Module) -> None:
        """A thinking config built away from any call we could connect it to."""
        for node in ast.walk(tree):
            if self._is_budget_tokens(node) and id(node) not in self.claimed:
                self.report("MA001", node.lineno, rules.budget_tokens(self.assume_model))

    def _check_prefill(self, messages: ast.expr | None, scope: Scope, model: str | None) -> None:
        messages = scope.resolve(messages)
        if not isinstance(messages, ast.List) or not messages.elts:
            return
        last = scope.resolve(messages.elts[-1])
        if not isinstance(last, ast.Dict) or _const(_dict_get(last, "role")) != "assistant":
            return
        # Echoing `response.content` is how a `pause_turn` gets resumed; only literal text is a
        # prefill we can be sure of.
        content = scope.resolve(_dict_get(last, "content"))
        literal = isinstance(content, ast.Constant | ast.JoinedStr) or (
            isinstance(content, ast.List)
            and all(
                isinstance(block, ast.Dict) and _const(_dict_get(block, "type")) == "text"
                for block in content.elts
            )
        )
        if literal:
            self.report("MA004", last.lineno, rules.prefill(model))

    def check_responses(self, nodes: list[ast.AST], scope: Scope) -> None:
        response_names: dict[str, int] = {}
        for node in nodes:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and self._yields_response(node.value):
                    response_names[target.id] = node.lineno
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "content"
                and isinstance(node.value, ast.Call)
                and self._yields_response(node.value)
            ):
                self.report("MA009", node.lineno, rules.missing_stop_reason("<call>"))
        for name, line in response_names.items():
            self._check_response_usage(name, line, nodes)

    @staticmethod
    def _yields_response(value: ast.expr) -> bool:
        if isinstance(value, ast.Await):
            value = value.value
        if not isinstance(value, ast.Call):
            return False
        if _endpoint(value) in RESPONSE_METHODS:
            return True
        name = dotted(value.func)
        return bool(name) and name.endswith("get_final_message")

    def _check_response_usage(self, name: str, line: int, nodes: list[ast.AST]) -> None:
        attributes: set[str] = set()
        attribute_values: set[int] = set()
        compared: set[str] = set()
        stop_reason_nodes: set[int] = set()

        for node in nodes:
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == name
            ):
                attributes.add(node.attr)
                attribute_values.add(id(node.value))
                if node.attr == "stop_reason":
                    stop_reason_nodes.add(id(node))

        branch_nodes: set[int] = set()
        for node in nodes:
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                if any(id(o) in stop_reason_nodes for o in operands):
                    branch_nodes.update(id(o) for o in operands if id(o) in stop_reason_nodes)
                    for operand in operands:
                        for inner in ast.walk(operand):
                            if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                                compared.add(inner.value)
            elif isinstance(node, ast.Match) and id(node.subject) in stop_reason_nodes:
                branch_nodes.add(id(node.subject))
                for case in node.cases:
                    for inner in ast.walk(case.pattern):
                        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                            compared.add(inner.value)

        # Handed on, returned, or serialised: whoever receives it may do the checking.
        escapes = any(
            isinstance(node, ast.Name)
            and node.id == name
            and isinstance(node.ctx, ast.Load)
            and id(node) not in attribute_values
            for node in nodes
        ) or bool(attributes & SERIALISERS)
        if escapes:
            return
        if "stop_reason" not in attributes:
            if "content" in attributes:
                self.report("MA009", line, rules.missing_stop_reason(name))
            return
        if stop_reason_nodes == branch_nodes and "refusal" not in compared:
            self.report("MA010", line, rules.no_refusal_branch(name))
