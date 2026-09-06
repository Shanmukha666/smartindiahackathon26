"""Fail pre/post release if schema or immutable QA-to-corpus audit references are inconsistent."""
from __future__ import annotations

import asyncio
import os

import asyncpg


async def main() -> None:
    connection = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        revision = await connection.fetchval("SELECT version_num FROM alembic_version")
        dangling = await connection.fetchval(
            """SELECT count(*) FROM qa_log AS log
               LEFT JOIN corpus_chunks AS chunk ON chunk.id::text = ANY(log.retrieved_chunk_ids)
               WHERE cardinality(log.retrieved_chunk_ids) > 0 AND chunk.id IS NULL"""
        )
        multiple_active = await connection.fetchval(
            """SELECT count(*) FROM (SELECT instrument FROM corpus_documents
               WHERE is_active GROUP BY instrument HAVING count(*) > 1) AS invalid"""
        )
        if dangling or multiple_active:
            raise RuntimeError(f"release audit check failed: dangling_qa_chunks={dangling}, multiple_active={multiple_active}")
        print(f"release check passed: alembic_revision={revision}, qa_log_chunk_references=intact")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
