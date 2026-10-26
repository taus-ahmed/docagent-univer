"""Request ids, a path-only access log and JSON logs (Part 2.8)."""
import json
import logging


def test_every_answer_has_a_request_id_and_a_safe_one_is_kept(client):
    r = client.get("/health")
    assert len(r.headers["x-request-id"]) >= 8
    assert client.get("/health", headers={"X-Request-ID": "abc-12345678"}).headers["x-request-id"] == "abc-12345678"
    bad = client.get("/health", headers={"X-Request-ID": "<script>alert(1)</script>"})
    assert bad.headers["x-request-id"] != "<script>alert(1)</script>"


def test_the_access_log_has_no_query_string_and_the_request_id(client, auth, caplog):
    caplog.set_level(logging.INFO, logger="docagent.access")
    r = client.get("/api/jobs?token=QZXTOKEN&name=secret.pdf", headers=auth["acme2"])
    lines = [rec for rec in caplog.records if rec.name == "docagent.access"]
    assert lines, "no access log line"
    text = " ".join(rec.getMessage() for rec in lines)
    assert "/api/jobs" in text and "QZXTOKEN" not in text and "secret.pdf" not in text
    assert r.headers["x-request-id"]


def test_records_made_during_a_request_carry_its_id(client, auth, caplog):
    from app.core.observability import RequestIdFilter
    caplog.handler.addFilter(RequestIdFilter())
    caplog.set_level(logging.INFO)
    r = client.get("/api/jobs", headers={**auth["acme2"], "X-Request-ID": "req-abcdef12"})
    access = [rec for rec in caplog.records if rec.name == "docagent.access"]
    assert any(getattr(rec, "request_id", "") == "req-abcdef12" for rec in access)


def test_json_format_is_one_object_per_line_and_holds_no_token(client, auth):
    from app.core.observability import JsonFormatter, RequestIdFilter
    rec = logging.LogRecord("docagent.access", logging.INFO, __file__, 1, "GET %s 200", ("/api/jobs",), None)
    RequestIdFilter().filter(rec)
    line = JsonFormatter().format(rec)
    obj = json.loads(line)
    assert set(obj) >= {"ts", "level", "logger", "request_id", "msg"} and obj["msg"] == "GET /api/jobs 200"
    tok = auth["acme2"]["Authorization"].split()[1]
    assert tok not in line
