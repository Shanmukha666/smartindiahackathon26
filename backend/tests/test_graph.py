import pytest

from app.graph import (
    AsyncpgGraphRepository,
    EntityType,
    GraphEntity,
    RelationshipType,
    entity_from_row,
    relationship_from_row,
)


def test_graph_vocabulary_contains_required_entity_and_relationship_types() -> None:
    assert set(EntityType) == {
        EntityType.INSTRUMENT,
        EntityType.SECTION,
        EntityType.TREATY,
        EntityType.FORMULATION_CATEGORY,
        EntityType.REGISTRY_RECORD,
    }
    assert set(RelationshipType) == {
        RelationshipType.CITES,
        RelationshipType.SUPERSEDES,
        RelationshipType.APPLIES_TO_CATEGORY,
        RelationshipType.CROSS_REFERENCES,
    }


def test_entity_from_row_preserves_graph_entity_fields() -> None:
    entity = entity_from_row(
        {"id": 4, "entity_type": "Treaty", "name": "WIPO GRATK Treaty", "properties": {"year": 2024}}
    )

    assert entity == GraphEntity(4, EntityType.TREATY, "WIPO GRATK Treaty", {"year": 2024})


def test_relationship_from_row_preserves_jsonb_text_properties() -> None:
    relationship = relationship_from_row(
        {
            "source_id": 1,
            "source_type": "Section",
            "source_name": "Patents Act, 1970 - Section 3(p)",
            "source_properties": "{}",
            "relationship_type": "APPLIES_TO_CATEGORY",
            "relationship_properties": '{"backfill":true}',
            "target_id": 2,
            "target_type": "FormulationCategory",
            "target_name": "classical",
            "target_properties": "{}",
        }
    )

    assert relationship.relationship_type is RelationshipType.APPLIES_TO_CATEGORY
    assert relationship.target.name == "classical"
    assert relationship.properties == {"backfill": True}


@pytest.mark.asyncio
async def test_connect_rejects_self_referential_edges_before_database_access() -> None:
    repository = AsyncpgGraphRepository(pool=None)
    entity = GraphEntity(7, EntityType.SECTION, "Patents Act, 1970 - Section 3(p)", {})

    with pytest.raises(ValueError, match="distinct entities"):
        await repository.connect(entity, RelationshipType.APPLIES_TO_CATEGORY, entity)
