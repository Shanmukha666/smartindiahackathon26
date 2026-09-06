from pathlib import Path

import pytest

from classification import Category, DecisionTree, TrailStep, load_tree

EXPECTED_CATEGORIES: set[Category] = {
    "classical/generic",
    "patent-or-proprietary",
    "new/non-classical drug",
    "phytopharmaceutical",
    "Ayurveda-Aahar/nutraceutical",
    "cosmetic",
}


def walk_all_paths(tree: DecisionTree) -> list[str]:
    terminal_categories: list[str] = []

    def walk(node_id: str, trail: list[TrailStep]) -> None:
        node = tree.document.nodes[node_id]
        if node.type == "result":
            terminal_categories.append(node.category)
            return
        for index, _option in enumerate(node.options):
            step = tree.advance(trail, index)
            if step.result is not None:
                terminal_categories.append(step.result.category)
            else:
                next_node = tree.document.nodes[step.trail[-1].node_id].options[index].next
                walk(next_node, step.trail)

    walk(tree.start, [])
    return terminal_categories


def test_every_default_path_terminates_in_a_defined_result() -> None:
    tree = load_tree()
    categories = walk_all_paths(tree)
    assert set(categories) == EXPECTED_CATEGORIES
    assert len(categories) >= len(EXPECTED_CATEGORIES)


def test_tree_rejects_missing_branch_targets() -> None:
    with pytest.raises(ValueError, match="missing node"):
        from classification import TreeDocument

        TreeDocument.model_validate(
            {
                "version": 1,
                "start": "start",
                "nodes": {
                    "start": {
                        "type": "question",
                        "prompt": "Question",
                        "options": [{"label": "Broken", "next": "missing"}],
                    }
                },
            }
        )


def test_alternate_yaml_changes_behavior_without_python_changes() -> None:
    fixture = Path(__file__).parent / "fixtures" / "alternate_classification.yaml"
    tree = load_tree(fixture)
    first = tree.initial()
    assert first.question == "Alternate expert question"
    final = tree.advance(first.trail, 0)
    assert final.result is not None
    assert final.result.regulatory_path == "Alternate regulatory path"
