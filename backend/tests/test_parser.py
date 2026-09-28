"""Milestone 2: the parser must never crash on bad input, and must count
malformed lines instead (SPEC.md section 6.2)."""

from __future__ import annotations

from app.models import AppEvent, AuditEvent
from app.parse.parser import Parser

VALID_APP = (
    '{"ts":"2026-09-28T13:00:01.123Z","type":"app","service":"prior_auth","level":"ERROR",'
    '"priority":"urgent","request_id":"PA-88213","patient_id":"P-000123",'
    '"status":500,"latency_ms":820,"msg":"Clinical rules engine timeout"}'
)
VALID_AUDIT = (
    '{"ts":"2026-09-28T13:00:02.004Z","type":"audit","user_id":"U-104","role":"care_manager",'
    '"action":"VIEW_RECORD","patient_id":"P-000877","patient_region":"TN-North","user_region":"TN-North"}'
)


def test_parses_valid_app_line():
    parser = Parser()
    result = parser.parse_line(VALID_APP)
    assert isinstance(result, AppEvent)
    assert result.service == "prior_auth"
    assert parser.malformed_lines == 0


def test_parses_valid_audit_line():
    parser = Parser()
    result = parser.parse_line(VALID_AUDIT)
    assert isinstance(result, AuditEvent)
    assert result.user_id == "U-104"
    assert parser.malformed_lines == 0


def test_invalid_json_is_counted_not_raised():
    parser = Parser()
    assert parser.parse_line("not json at all {{{") is None
    assert parser.malformed_lines == 1


def test_valid_json_wrong_schema_is_counted():
    parser = Parser()
    assert parser.parse_line('{"type":"app","service":"not-a-real-service"}') is None
    assert parser.malformed_lines == 1


def test_unknown_type_is_counted():
    parser = Parser()
    assert parser.parse_line('{"type":"something-else","x":1}') is None
    assert parser.malformed_lines == 1


def test_json_array_instead_of_object_is_counted():
    parser = Parser()
    assert parser.parse_line("[1, 2, 3]") is None
    assert parser.malformed_lines == 1


def test_malformed_lines_accumulate_across_calls():
    parser = Parser()
    parser.parse_line("garbage")
    parser.parse_line(VALID_APP)
    parser.parse_line("more garbage")
    assert parser.malformed_lines == 2
