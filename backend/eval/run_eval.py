from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.prompt_policy import SYSTEM_PROMPT_POLICY, SYSTEM_PROMPT_SHA256, SYSTEM_PROMPT_VERSION
from classification import load_tree


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    kind: str
    question: str
    jurisdiction: str
    expected_citation_ids: set[str]
    expected_category: str | None
    should_abstain: bool
    answers: list[int]


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    kind: str
    citation_correct: bool | None
    predicted_abstain: bool | None
    expected_abstain: bool | None
    classification_correct: bool | None


def load_cases(path: Path) -> list[EvalCase]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    for raw in document.get("cases", []):
        cases.append(
            EvalCase(
                case_id=raw["id"],
                kind=raw["kind"],
                question=raw["question"],
                jurisdiction=raw["jurisdiction"],
                expected_citation_ids={str(item) for item in raw.get("expected_citation_ids", [])},
                expected_category=raw.get("expected_category"),
                should_abstain=bool(raw["should_abstain"]),
                answers=[int(item) for item in raw.get("answers", [])],
            )
        )
    if not cases:
        raise ValueError("evaluation YAML contains no cases")
    return cases


def validate_prompt_manifest(path: Path) -> dict[str, str]:
    """Fail closed when a prompt policy changes without a versioned eval manifest."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    version = manifest.get("version")
    fingerprint = manifest.get("sha256")
    if not isinstance(version, str) or not isinstance(fingerprint, str):
        raise TypeError("prompt manifest requires string version and sha256 fields")
    if version != SYSTEM_PROMPT_VERSION or fingerprint != SYSTEM_PROMPT_SHA256:
        raise SystemExit(
            "Prompt policy is not versioned for evaluation: update the policy version and "
            "backend/eval/prompt_manifest.json before merging."
        )
    if fingerprint != hashlib.sha256(SYSTEM_PROMPT_POLICY.encode("utf-8")).hexdigest():
        raise SystemExit("Prompt policy fingerprint is inconsistent")
    return {"version": version, "sha256": fingerprint}


class EvalClient:
    def __init__(self, base_url: str, offline: bool) -> None:
        self.base_url = base_url.rstrip("/")
        self.offline = offline
        self.tree = load_tree() if offline else None

    async def ask(self, case: EvalCase) -> tuple[set[str] | None, bool | None]:
        if self.offline:
            # Offline mode has no corpus, providers, or API under test.  Returning
            # fixture expectations here would turn quality metrics into tautologies.
            return None, None
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{self.base_url}/ask",
                json={"query": case.question, "jurisdiction": case.jurisdiction, "session_id": f"eval-{case.case_id}"},
            )
            response.raise_for_status()
            payload = response.json()
            return {str(item) for item in payload.get("citations", [])}, bool(payload["abstain"])

    async def classify(self, case: EvalCase) -> str | None:
        if self.offline:
            assert self.tree is not None
            step = self.tree.initial()
            for answer_index in case.answers:
                step = self.tree.advance(step.trail, answer_index)
            return step.result.category if step.result else None
        trail: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/classify/next",
                json={"session_id": f"eval-{case.case_id}", "trail": trail, "answer_index": None},
            )
            response.raise_for_status()
            payload = response.json()
            for answer_index in case.answers:
                response = await client.post(
                    f"{self.base_url}/classify/next",
                    json={"session_id": f"eval-{case.case_id}", "trail": payload["trail"], "answer_index": answer_index},
                )
                response.raise_for_status()
                payload = response.json()
            return cast(str | None, payload.get("result", {}).get("category"))


async def evaluate(cases: list[EvalCase], client: EvalClient) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        if case.kind == "classification":
            category = await client.classify(case)
            results.append(CaseResult(case.case_id, case.kind, None, None, None, category == case.expected_category))
        elif case.kind == "ask":
            citations, abstained = await client.ask(case)
            results.append(CaseResult(
                case.case_id,
                case.kind,
                citations == case.expected_citation_ids if citations is not None else None,
                abstained,
                case.should_abstain,
                None,
            ))
        else:
            raise ValueError(f"unsupported evaluation case kind: {case.kind}")
    return results


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def report(results: list[CaseResult]) -> dict[str, Any]:
    ask_results = [result for result in results if result.kind == "ask"]
    classification_results = [result for result in results if result.kind == "classification"]
    true_positive = sum(result.predicted_abstain is True and result.expected_abstain is True for result in ask_results)
    false_positive = sum(result.predicted_abstain is True and result.expected_abstain is False for result in ask_results)
    false_negative = sum(result.predicted_abstain is False and result.expected_abstain is True for result in ask_results)
    ask_was_evaluated = any(result.citation_correct is not None for result in ask_results)
    return {
        "cases": len(results),
        "ask_evaluation": "evaluated" if ask_was_evaluated else "not_evaluated_offline",
        "citation_correctness_rate": ratio(sum(result.citation_correct is True for result in ask_results), len(ask_results)) if ask_was_evaluated else None,
        "abstention_precision": ratio(true_positive, true_positive + false_positive) if ask_was_evaluated else None,
        "abstention_recall": ratio(true_positive, true_positive + false_negative) if ask_was_evaluated else None,
        "classification_accuracy": ratio(sum(result.classification_correct is True for result in classification_results), len(classification_results)),
        "failed_cases": [result.case_id for result in results if result.citation_correct is False or result.classification_correct is False or (result.predicted_abstain is not None and result.expected_abstain != result.predicted_abstain if result.kind == "ask" else False)],
    }


def enforce_baseline(metrics: dict[str, Any], baseline_path: Path | None, max_regression: float) -> None:
    if baseline_path is None:
        return
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    failures = []
    for metric in ("citation_correctness_rate", "abstention_precision"):
        if metrics.get(metric) is None or baseline.get(metric) is None:
            continue
        if metrics[metric] < baseline[metric] - max_regression:
            failures.append(f"{metric}={metrics[metric]:.3f} below baseline {baseline[metric]:.3f} by more than {max_regression:.3f}")
    if failures:
        raise SystemExit("Evaluation regression: " + "; ".join(failures))


async def main_async(args: argparse.Namespace) -> None:
    prompt_policy = validate_prompt_manifest(args.prompt_manifest)
    cases = load_cases(args.cases)
    results = await evaluate(cases, EvalClient(args.base_url, args.offline))
    metrics = report(results)
    metrics["system_prompt"] = prompt_policy
    print(json.dumps(metrics, indent=2, sort_keys=True))
    enforce_baseline(metrics, args.compare_to, args.max_regression)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate /ask and /classify/next against YAML cases")
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.yaml"))
    parser.add_argument("--base-url", default=os.getenv("EVAL_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--offline", action="store_true", help="Run deterministic evaluator checks without a backend")
    parser.add_argument("--compare-to", type=Path)
    parser.add_argument("--prompt-manifest", type=Path, default=Path(__file__).with_name("prompt_manifest.json"))
    parser.add_argument("--max-regression", type=float, default=float(os.getenv("EVAL_MAX_REGRESSION", "0.05")))
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
