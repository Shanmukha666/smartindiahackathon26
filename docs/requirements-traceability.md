# Project-requirements traceability

This traceability record maps the supplied **IP-SAKTI Sahayak Project Requirement Document** (Problem Statement 26045) to the repository as of 2026-09-08. “Partial” does not mean complete; it identifies the exact remaining work.

| Requirement area | Status | Repository evidence / boundary |
| --- | --- | --- |
| India / International toggle and structurally separated answers | Implemented | `jurisdiction` accepts `IN`, `INTL`, and `BOTH`; `BOTH` requires split answer sections. Corpus breadth is still partial. |
| Six-way formulation classification | Implemented | YAML decision tree returns all six required categories, regulatory path, IP routes, TKDL guidance, ABS note, and action checklist. |
| ABS helper and TKDL pointer | Implemented, informational | Classification supplies a provenance/approval checklist and official TKDL link. It does not decide legal applicability or query restricted TKDL data. |
| Mandatory citations, confidence, abstention, disclaimer | Implemented | Citation validation, retrieval/reranker confidence checks, abstention, and standing disclaimer are tested. |
| Escalation | Implemented | Authenticated escalation with audit record and production webhook configuration. A real facilitator/on-call recipient must be configured externally. |
| Free official-source access | Implemented as user-operated links | Links to IP India, WIPO PATENTSCOPE, WIPO Global Brand Database, and TKDL information. No automated registry search is claimed. |
| Paid-source access | Deferred by stated phase plan | Explicit consent/audit and credential-encryption framework exist; production has no provider connector until an allowlisted vendor and user subscription are selected. |
| National corpus: all listed Acts/Rules | Partial | Current corpus covers Patents s.3(p), Biological Diversity s.21, Drugs/Cosmetics overview, GI, Trade Marks, and Designs. Copyright, PPV&FR, Magic Remedies, FSSAI Ayurveda-Aahar, Patent Rules 2024, Biodiversity amendment/rules, pharmacopoeia, registry records, and case law require reviewer-approved dedicated corpus PRs. |
| International corpus: all listed instruments | Partial | TRIPS overview is included. CBD, Nagoya, WIPO GRATK, PCT, Madrid, Hague, Budapest, and selected export-market access sources require authoritative, reviewer-approved corpus PRs. |
| Multilingual text delivery | Partial | Bhashini query translation and language audit paths are implemented; interface chrome remains English until reviewed translations are added. |
| Full multilingual voice experience | Deferred by requirements | Backend Bhashini ASR/TTS endpoints exist; browser recording UX and live Bhashini credentials are outside the current MVP. |
| Knowledge graph / agentic multi-source orchestration | Partial / later phase | Relational graph and bounded tool orchestration exist; broad multi-source legal reasoning remains explicitly deferred. |
| Corpus currency, governance, auditability | Implemented process; external review required | Version/provenance, quarterly review workflow, source review rules, review queue, and rollback documentation are present. Qualified legal review and branch protection are external controls. |
| Production availability, security, privacy | Code controls implemented; deployment verification outstanding | Production guardrails, rate-limit contract, secret handling, observability, migration/release procedures, and smoke tests exist. Cloud setup, WIF, Secret Manager, monitoring receiver, test evidence, and live RAG evaluation are required before production approval. |

## Release rule

The project must not be described as production-ready while the partial or external-control rows above remain open. The current scope is a source-cited demonstration/MVP with transparent safety boundaries, not a substitute for licensed legal advice.
