from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app import main
from app.auth import issue_test_token


def test_admin_review_queue_returns_pending_stale_answers(monkeypatch) -> None:
    class FakeRepository:
        @classmethod
        async def create(cls, database_url: str):
            return cls()

        async def close(self) -> None:
            pass

        async def list_review_queue(self, limit: int):
            assert limit == 100
            return [{
                "id": 7,
                "qa_log_id": 21,
                "question": "What does Section 3(p) exclude?",
                "answer_json": {"answer": "Traditional knowledge. [42]"},
                "changed_instrument": "Patents Act, 1970",
                "changed_section": "Section 3(p)",
                "relationship_types": ["DIRECT_CHANGE", "SUPERSEDES"],
                "status": "pending",
                "created_at": datetime(2026, 9, 6, tzinfo=UTC),
            }]

    monkeypatch.setattr(main, "AsyncpgCorpusRepository", FakeRepository)
    response = TestClient(main.app).get("/admin/review-queue", headers={"Authorization": f"Bearer {issue_test_token('legal-reviewer', roles=['legal_reviewer'])}"})

    assert response.status_code == 200
    assert response.json() == [{
        "id": 7,
        "qa_log_id": 21,
        "question": "What does Section 3(p) exclude?",
        "answer_json": {"answer": "Traditional knowledge. [42]"},
        "changed_instrument": "Patents Act, 1970",
        "changed_section": "Section 3(p)",
        "relationship_types": ["DIRECT_CHANGE", "SUPERSEDES"],
        "status": "pending",
        "created_at": "2026-09-06T00:00:00+00:00",
    }]


def test_legal_reviewer_must_close_pending_item_with_a_note(monkeypatch) -> None:
    class FakeRepository:
        @classmethod
        async def create(cls, database_url: str):
            return cls()

        async def close(self) -> None:
            pass

        async def resolve_review_queue_item(self, queue_id: int, status: str, reviewer: str, resolution_note: str) -> bool:
            assert (queue_id, status, reviewer, resolution_note) == (7, "reviewed", "legal-reviewer", "Verified against India Code")
            return True

    monkeypatch.setattr(main, "AsyncpgCorpusRepository", FakeRepository)
    client = TestClient(main.app)
    payload = {"status": "reviewed", "resolution_note": "Verified against India Code"}
    engineer = client.patch("/admin/review-queue/7", json=payload, headers={"Authorization": f"Bearer {issue_test_token('engineer', roles=['admin'])}"})
    assert engineer.status_code == 403
    response = client.patch("/admin/review-queue/7", json=payload, headers={"Authorization": f"Bearer {issue_test_token('legal-reviewer', roles=['legal_reviewer'])}"})
    assert response.status_code == 204
