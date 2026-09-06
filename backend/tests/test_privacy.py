from typing import ClassVar

from fastapi.testclient import TestClient

from app import main
from app.auth import current_user


def test_data_deletion_physically_removes_records_except_legal_hold() -> None:
    class FakeRepository:
        rows: ClassVar[list[dict[str, object]]] = [
            {"user_id": "person-1", "question": "delete me", "legal_hold": False},
            {"user_id": "person-1", "question": "retain on hold", "legal_hold": True},
        ]

        @classmethod
        async def create(cls, database_url: str):
            return cls()

        async def close(self) -> None:
            pass

        async def delete_user_data(self, user_id: str):
            deleted = [row for row in self.rows if row["user_id"] == user_id and not row["legal_hold"]]
            type(self).rows = [row for row in self.rows if row not in deleted]
            return {"qa_log": len(deleted), "escalations": 0, "paid_source_grants": 0, "paid_source_credentials": 0}

        async def export_user_data(self, user_id: str):
            return {"qa_log": [row for row in self.rows if row["user_id"] == user_id], "escalations": [], "paid_source_grants": []}

    main.app.dependency_overrides[current_user] = lambda: "person-1"
    try:
        monkeypatch_target = main.AsyncpgCorpusRepository
        main.AsyncpgCorpusRepository = FakeRepository
        client = TestClient(main.app)
        deleted = client.delete("/privacy/data")
        exported = client.get("/privacy/export")
    finally:
        main.AsyncpgCorpusRepository = monkeypatch_target
        main.app.dependency_overrides.clear()

    assert deleted.status_code == 200
    assert deleted.json()["deleted"]["qa_log"] == 1
    assert [row["question"] for row in exported.json()["qa_log"]] == ["retain on hold"]
