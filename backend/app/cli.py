from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from .config import get_settings
from .ingest import AsyncpgCorpusRepository, VoyageEmbedder, ingest_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ip-sakti-sahayak")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Ingest versioned documents from the corpus directory")
    ingest.add_argument(
        "--corpus-dir",
        type=Path,
        default=Path(os.environ.get("CORPUS_DIR", "/corpus")),
        help="Directory containing documents with YAML frontmatter (default: /corpus)",
    )
    rollback = commands.add_parser("rollback-corpus", help="Activate a retained corpus version")
    rollback.add_argument("--instrument", required=True)
    rollback.add_argument("--version-tag", required=True)
    return parser


async def run_ingest(corpus_dir: Path) -> None:
    settings = get_settings()
    repository = await AsyncpgCorpusRepository.create(settings.database_url.get_secret_value())
    try:
        async with VoyageEmbedder(settings) as embedder:
            stats = await ingest_directory(corpus_dir, repository, embedder)
    finally:
        await repository.close()
    print(json.dumps(stats.__dict__, sort_keys=True))


async def run_corpus_rollback(instrument: str, version_tag: str) -> None:
    settings = get_settings()
    repository = await AsyncpgCorpusRepository.create(settings.database_url.get_secret_value())
    try:
        document_id = await repository.rollback_corpus_version(instrument, version_tag)
    finally:
        await repository.close()
    print(json.dumps({"instrument": instrument, "version_tag": version_tag, "active_document_id": document_id}))


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "ingest":
        asyncio.run(run_ingest(args.corpus_dir))
    if args.command == "rollback-corpus":
        asyncio.run(run_corpus_rollback(args.instrument, args.version_tag))


if __name__ == "__main__":
    main()
