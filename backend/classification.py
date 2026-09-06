from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal[
    "classical/generic",
    "patent-or-proprietary",
    "new/non-classical drug",
    "phytopharmaceutical",
    "Ayurveda-Aahar/nutraceutical",
    "cosmetic",
]


class TrailStep(BaseModel):
    node_id: str = Field(min_length=1)
    answer_index: int = Field(ge=0)


class DecisionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    next: str = Field(min_length=1)


class QuestionNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["question"]
    prompt: str = Field(min_length=1)
    options: list[DecisionOption] = Field(min_length=1)


class ResultNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["result"]
    category: Category
    regulatory_path: str = Field(min_length=1)
    ip_posture: str = Field(min_length=1)
    abs_note: str = Field(min_length=1)


class TreeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    start: str = Field(min_length=1)
    nodes: dict[str, QuestionNode | ResultNode] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_graph(self) -> TreeDocument:
        if self.start not in self.nodes:
            raise ValueError(f"start node does not exist: {self.start}")
        for node_id, node in self.nodes.items():
            if isinstance(node, QuestionNode):
                for option in node.options:
                    if option.next not in self.nodes:
                        raise ValueError(f"{node_id} points to missing node {option.next}")

        reachable: set[str] = set()
        pending = [self.start]
        while pending:
            node_id = pending.pop()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            node = self.nodes[node_id]
            if isinstance(node, QuestionNode):
                pending.extend(option.next for option in node.options)
        unreachable = set(self.nodes) - reachable
        if unreachable:
            raise ValueError(f"unreachable nodes: {sorted(unreachable)}")

        for node_id in reachable:
            if not self._can_terminate(node_id, set()):
                raise ValueError(f"node has no terminating result path: {node_id}")
        return self

    def _can_terminate(self, node_id: str, visiting: set[str]) -> bool:
        if node_id in visiting:
            return False
        node = self.nodes[node_id]
        if isinstance(node, ResultNode):
            return True
        next_visiting = visiting | {node_id}
        return all(self._can_terminate(option.next, next_visiting) for option in node.options)


@dataclass(frozen=True)
class ClassificationResult:
    category: Category
    regulatory_path: str
    ip_posture: str
    abs_note: str


@dataclass(frozen=True)
class ClassificationStep:
    question: str | None
    options: list[str]
    result: ClassificationResult | None
    trail: list[TrailStep]


class DecisionTree:
    def __init__(self, document: TreeDocument) -> None:
        self.document = document

    @property
    def start(self) -> str:
        return self.document.start

    def initial(self) -> ClassificationStep:
        return self._step(self.document.start, [])

    def advance(self, trail: Sequence[TrailStep], answer_index: int) -> ClassificationStep:
        node_id = self.document.start
        for prior in trail:
            if prior.node_id != node_id:
                raise ValueError("trail does not follow the decision tree")
            node = self.document.nodes[node_id]
            if not isinstance(node, QuestionNode) or prior.answer_index >= len(node.options):
                raise ValueError("trail contains an invalid answer")
            node_id = node.options[prior.answer_index].next
        node = self.document.nodes[node_id]
        if not isinstance(node, QuestionNode):
            raise ValueError("trail is already complete")  # noqa: TRY004
        if answer_index < 0 or answer_index >= len(node.options):
            raise ValueError("answer_index is outside the current question")
        updated_trail = [*trail, TrailStep(node_id=node_id, answer_index=answer_index)]
        return self._step(node.options[answer_index].next, updated_trail)

    def _step(self, node_id: str, trail: list[TrailStep]) -> ClassificationStep:
        node = self.document.nodes[node_id]
        if isinstance(node, QuestionNode):
            return ClassificationStep(node.prompt, [option.label for option in node.options], None, trail)
        return ClassificationStep(
            None,
            [],
            ClassificationResult(
                category=node.category,
                regulatory_path=node.regulatory_path,
                ip_posture=node.ip_posture,
                abs_note=node.abs_note,
            ),
            trail,
        )


def load_tree(path: Path | str | None = None) -> DecisionTree:
    configured_path = path or os.environ.get("CLASSIFICATION_TREE_PATH")
    tree_path = Path(configured_path) if configured_path else Path(__file__).with_name("classification_tree.yaml")
    raw = yaml.safe_load(tree_path.read_text(encoding="utf-8"))
    return DecisionTree(TreeDocument.model_validate(raw))
