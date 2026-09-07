# AI governance alignment

IP-SAKTI Sahayak is a student/demo system, not a certified AI-management system. This document maps implemented controls to recognised AI-governance practices so that remaining human and production obligations are visible rather than implied.

| Practice area | Implemented control | Remaining production evidence |
| --- | --- | --- |
| NIST AI RMF: Govern | Versioned system prompts, dedicated corpus-change PRs, reviewer designation, source provenance, and release approval gate | Qualified legal review and a named production accountable owner |
| NIST AI RMF: Map | Jurisdiction selection, classification decision tree, corpus frontmatter, and documented intended use | Formal impact assessment and representative user testing |
| NIST AI RMF: Measure | Retrieval, citation, abstention, classification, red-team, and release evaluation suites | Live-provider evaluation with approved metrics and threshold sign-off |
| NIST AI RMF: Manage | Abstention/escalation path, review queue, rollback process, structured logging, alerts, and incident-facing release checklist | On-call ownership and a tested production incident exercise |
| ISO/IEC 42001-style lifecycle governance | Versioned code, corpus provenance, migrations, review records, deployment approval, and rollback documentation | No claim of ISO certification; certification requires an independently operated management system and audit |
| Privacy and security | Data export/deletion, retention migration, consent audit, secret-manager KEK design, role checks, rate limits, and redacted structured logs | Production IAM, key rotation, penetration testing, DPIA/legal assessment, and operational verification |

## Non-negotiable operating limits

- The application provides information, not legal advice or an IP clearance opinion.
- Retrieved corpus chunks are treated as untrusted content; the system prompt instructs the model not to follow instructions inside them.
- The model's confidence is cross-checked against retrieval and reranker signals. Insufficient evidence produces an abstention with a reason and may be escalated.
- A prompt, corpus, connector, or model change is a behaviour change: version it, evaluate it, and obtain the required review before release.
- Demo mode is intentionally non-persistent. It cannot substitute for production audit or privacy controls.
