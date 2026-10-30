from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from messages_api_lint.catalog import (
    DEPRECATED,
    MODEL_FACTS,
    RETIRED,
    RULES,
    RULES_WRITTEN,
    canonical_model,
)
from messages_api_lint.cli import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, main, rules_age_note

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_stale_example_fails_and_current_example_passes(capsys):
    assert main([str(EXAMPLES / "stale_app.py")]) == EXIT_FINDINGS
    out = capsys.readouterr().out
    for rule in RULES:
        assert rule in out
    assert main([str(EXAMPLES / "current_app.py"), "--fail-on", "info"]) == EXIT_OK


def test_json_output_carries_the_rule_date_and_citations(capsys):
    main([str(EXAMPLES / "stale_app.py"), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["rules_written"] == RULES_WRITTEN
    assert all(f["citations"] for f in payload["findings"])
    assert payload["findings"][0]["engine"] == "ast"


def test_every_rule_cites_a_section():
    assert all(rule.citations for rule in RULES.values())


def test_rules_written_is_a_real_date():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", RULES_WRITTEN)
    dt.date.fromisoformat(RULES_WRITTEN)


def test_age_note_appears_only_when_old():
    written = dt.date.fromisoformat(RULES_WRITTEN)
    assert rules_age_note(written) is None
    note = rules_age_note(written + dt.timedelta(days=400))
    assert note
    assert "400 days old" in note


def test_directory_walk_skips_vendored_code(tmp_path, capsys):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text('const m = "claude-2.1";\n')
    (tmp_path / "a.py").write_text('M = "claude-2.1"\n')
    assert main([str(tmp_path)]) == EXIT_FINDINGS
    out = capsys.readouterr().out
    assert "1 files" in out
    assert "node_modules" not in out


def test_inline_suppression(tmp_path, capsys):
    path = tmp_path / "a.py"
    path.write_text('M = "claude-2.1"  # messages-api-lint: ignore[MA007]\nN = "claude-2.0"\n')
    main([str(path), "--format", "json", "--fail-on", "never"])
    assert [f["line"] for f in json.loads(capsys.readouterr().out)["findings"]] == [2]
    path.write_text('M = "claude-2.1"  # messages-api-lint: ignore\n')
    assert main([str(path)]) == EXIT_OK


def test_suppression_for_another_rule_does_not_apply(tmp_path):
    path = tmp_path / "a.py"
    path.write_text('M = "claude-2.1"  # messages-api-lint: ignore[MA001]\n')
    assert main([str(path)]) == EXIT_FINDINGS


def test_module_dict_spread_in_function_is_reported_once(tmp_path, capsys):
    path = tmp_path / "a.py"
    path.write_text(
        'P = {"model": "claude-opus-5-5", "messages": [], "top_k": 3}\n'
        "def f():\n"
        "    return client.messages.create(**P)\n"
    )
    main([str(path), "--format", "json"])
    found = [f for f in json.loads(capsys.readouterr().out)["findings"] if f["rule"] == "MA002"]
    assert len(found) == 1


def test_syntax_error_is_reported_and_others_continue(tmp_path, capsys):
    (tmp_path / "bad.py").write_text("def (:\n")
    (tmp_path / "good.py").write_text('M = "claude-2.1"\n')
    assert main([str(tmp_path)]) == EXIT_FINDINGS
    captured = capsys.readouterr()
    assert "invalid Python" in captured.err
    assert "claude-2.1" in captured.out


def test_usage_errors(tmp_path):
    assert main([]) == EXIT_USAGE
    assert main([str(tmp_path / "nope")]) == EXIT_USAGE
    assert main([str(tmp_path), "--ignore", "MA999"]) == EXIT_USAGE


def test_select_and_ignore(capsys):
    path = str(EXAMPLES / "stale_app.py")
    main([path, "--select", "MA007", "--format", "json"])
    assert {f["rule"] for f in json.loads(capsys.readouterr().out)["findings"]} == {"MA007"}
    main([path, "--ignore", "MA007", "--format", "json"])
    assert "MA007" not in {f["rule"] for f in json.loads(capsys.readouterr().out)["findings"]}


def test_list_rules_prints_date_and_citations(capsys):
    assert main(["--list-rules"]) == EXIT_OK
    out = capsys.readouterr().out
    assert RULES_WRITTEN in out
    assert "shared/model-migration.md §" in out


def test_check_citations_passes_on_a_matching_copy_and_fails_on_drift(tmp_path, capsys):
    for rule in RULES.values():
        for citation in rule.citations:
            path = tmp_path / citation.file
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"## {citation.section}\n")
    assert main(["--check-citations", str(tmp_path)]) == EXIT_OK

    first = next(iter(RULES.values())).citations[0]
    path = tmp_path / first.file
    path.write_text(path.read_text().replace(first.section, "Renamed"))
    assert main(["--check-citations", str(tmp_path)]) == EXIT_FINDINGS
    assert "not found" in capsys.readouterr().out


def test_canonical_model():
    assert canonical_model("claude-opus-5-5") == "claude-opus-5-5"
    assert canonical_model("claude-opus-4-5-20251101") == "claude-opus-4-5"
    assert canonical_model("us.anthropic.claude-opus-5-5") == "claude-opus-5-5"
    assert canonical_model("claude-opus-4-20250514") == "claude-opus-4-0"
    assert canonical_model("claude-nonesuch") is None
    assert canonical_model(None) is None


def test_tables_do_not_overlap():
    assert not set(RETIRED) & set(DEPRECATED)
    assert not set(RETIRED) & set(MODEL_FACTS)
