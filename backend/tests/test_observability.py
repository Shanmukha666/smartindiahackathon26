import json
import logging

from fastapi.testclient import TestClient

from app.main import app
from app.observability import JsonFormatter, request_id_context

client = TestClient(app)


def test_request_id_is_returned_and_logged(caplog) -> None:
    request_id = "test-request-id"
    with caplog.at_level(logging.INFO):
        response = client.get("/health", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id
    assert any(record.message == "request.completed" for record in caplog.records)


def test_json_formatter_includes_request_id_and_event_fields() -> None:
    token = request_id_context.set("formatter-request-id")
    try:
        record = logging.LogRecord("test", logging.INFO, "", 0, "request.completed", (), None)
        record.method = "GET"
        record.path = "/health"
        record.status_code = 200
        event = json.loads(JsonFormatter().format(record))
    finally:
        request_id_context.reset(token)

    assert event["request_id"] == "formatter-request-id"
    assert event["method"] == "GET"
    assert event["status_code"] == 200