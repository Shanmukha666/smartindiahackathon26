"""PostgreSQL adjacency-graph access for legal corpus entities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EntityType(StrEnum):
    INSTRUMENT = "Instrument"
    SECTION = "Section"
    TREATY = "Treaty"
    FORMULATION_CATEGORY = "FormulationCategory"
    REGISTRY_RECORD = "RegistryRecord"


class RelationshipType(StrEnum):
    CITES = "CITES"
    SUPERSEDES = "SUPERSEDES"
    APPLIES_TO_CATEGORY = "APPLIES_TO_CATEGORY"
    CROSS_REFERENCES = "CROSS_REFERENCES"


@dataclass(frozen=True)
class GraphEntity:
    id: int
    entity_type: EntityType
    name: str
    properties: dict[str, Any]


@dataclass(frozen=True)
class GraphRelationship:
    source: GraphEntity
    relationship_type: RelationshipType
    target: GraphEntity
    properties: dict[str, Any]


class AsyncpgGraphRepository:
    """Directed graph repository backed by graph_entities and graph_relationships."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def upsert_entity(
        self,
        entity_type: EntityType,
        name: str,
        properties: dict[str, Any] | None = None,
    ) -> GraphEntity:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO graph_entities (entity_type, name, properties)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (entity_type, name) DO UPDATE
                SET properties = graph_entities.properties || EXCLUDED.properties
                RETURNING id, entity_type, name, properties
                """,
                entity_type.value,
                name,
                json.dumps(properties or {}),
            )
        return entity_from_row(row)

    async def connect(
        self,
        source: GraphEntity,
        relationship_type: RelationshipType,
        target: GraphEntity,
        properties: dict[str, Any] | None = None,
    ) -> None:
        if source.id == target.id:
            raise ValueError("A graph relationship must connect distinct entities")
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO graph_relationships
                    (source_entity_id, target_entity_id, relationship_type, properties)
                VALUES ($1, $2, $3, $4::jsonb)
                ON CONFLICT (source_entity_id, target_entity_id, relationship_type) DO UPDATE
                SET properties = graph_relationships.properties || EXCLUDED.properties
                """,
                source.id,
                target.id,
                relationship_type.value,
                json.dumps(properties or {}),
            )

    async def outgoing(self, entity: GraphEntity) -> list[GraphRelationship]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT source.id AS source_id, source.entity_type AS source_type,
                       source.name AS source_name, source.properties AS source_properties,
                       relationship.relationship_type, relationship.properties AS relationship_properties,
                       target.id AS target_id, target.entity_type AS target_type,
                       target.name AS target_name, target.properties AS target_properties
                FROM graph_relationships AS relationship
                JOIN graph_entities AS source ON source.id = relationship.source_entity_id
                JOIN graph_entities AS target ON target.id = relationship.target_entity_id
                WHERE relationship.source_entity_id = $1
                ORDER BY relationship.relationship_type, target.entity_type, target.name
                """,
                entity.id,
            )
        return [relationship_from_row(row) for row in rows]

    async def lookup(self, entity_name: str, relation: RelationshipType) -> list[GraphRelationship]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT source.id AS source_id, source.entity_type AS source_type, source.name AS source_name,
                          source.properties AS source_properties, relationship.relationship_type,
                          relationship.properties AS relationship_properties, target.id AS target_id,
                          target.entity_type AS target_type, target.name AS target_name, target.properties AS target_properties
                   FROM graph_relationships AS relationship
                   JOIN graph_entities AS source ON source.id = relationship.source_entity_id
                   JOIN graph_entities AS target ON target.id = relationship.target_entity_id
                   WHERE lower(source.name) = lower($1) AND relationship.relationship_type = $2
                   ORDER BY target.entity_type, target.name""",
                entity_name, relation.value,
            )
        return [relationship_from_row(row) for row in rows]


def entity_from_row(row: Any) -> GraphEntity:
    return GraphEntity(
        id=int(row["id"]),
        entity_type=EntityType(row["entity_type"]),
        name=str(row["name"]),
        properties=json_object(row["properties"]),
    )


def relationship_from_row(row: Any) -> GraphRelationship:
    return GraphRelationship(
        source=GraphEntity(
            id=int(row["source_id"]),
            entity_type=EntityType(row["source_type"]),
            name=str(row["source_name"]),
            properties=json_object(row["source_properties"]),
        ),
        relationship_type=RelationshipType(row["relationship_type"]),
        target=GraphEntity(
            id=int(row["target_id"]),
            entity_type=EntityType(row["target_type"]),
            name=str(row["target_name"]),
            properties=json_object(row["target_properties"]),
        ),
        properties=json_object(row["relationship_properties"]),
    )


def json_object(value: Any) -> dict[str, Any]:
    """Normalize asyncpg JSONB values, which may be decoded or raw JSON text."""
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise ValueError("Graph properties must be a JSON object")  # noqa: TRY004
    return dict(decoded)
