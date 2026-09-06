import { useCallback, useEffect, useState } from "react";
import { t } from "./i18n/resources";

type Jurisdiction = "IN" | "INTL" | "BOTH";
type IndicLanguage = "en" | "hi" | "bn" | "gu" | "kn" | "ml" | "mr" | "or" | "pa" | "ta" | "te" | "ur";
type TrailStep = { node_id: string; answer_index: number };
type ClassificationResult = { category: string; regulatory_path: string; ip_posture: string; abs_note: string };
type ClassificationState = { complete: boolean; question: string | null; options: string[]; trail: TrailStep[]; result: ClassificationResult | null };
type RetrievedEvidence = { chunk_id: string; instrument: string; section: string; jurisdiction: "IN" | "INTL"; chunk_text: string; score: number };
type AskSection = { jurisdiction?: string; title?: string; text?: string; answer?: string };
type AskResponse = { mode: "single" | "split" | null; answer: string | null; sections: AskSection[] | null; citations: string[]; confidence: "high" | "medium" | "low" | null; abstain: boolean; reason: string | null; disclaimer: string };
type EscalationResponse = { tracking_id: string; priority: string; status: string };
type RetrieveResponse = { results: RetrievedEvidence[] };

const languages: { code: IndicLanguage; label: string }[] = [
  { code: "en", label: "English" }, { code: "hi", label: "Hindi" }, { code: "bn", label: "Bengali" }, { code: "gu", label: "Gujarati" },
  { code: "kn", label: "Kannada" }, { code: "ml", label: "Malayalam" }, { code: "mr", label: "Marathi" }, { code: "or", label: "Odia" },
  { code: "pa", label: "Punjabi" }, { code: "ta", label: "Tamil" }, { code: "te", label: "Telugu" }, { code: "ur", label: "Urdu" },
];

const api = async <T,>(path: string, body: unknown): Promise<T> => {
  const response = await fetch(`/api${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
};

const initialClassification: ClassificationState = { complete: false, question: null, options: [], trail: [], result: null };

function InlineCitations({ text }: { text: string }) {
  return <>{text.split(/(\[[^\]]+\])/g).map((part, index) => /^\[[^\]]+\]$/.test(part) ? <span className="citation-chip" key={`${part}-${index}`}>{part.slice(1, -1)}</span> : <span key={`${part}-${index}`}>{part}</span>)}</>;
}

function App() {
  const [jurisdiction, setJurisdiction] = useState<Jurisdiction>("BOTH");
  const [language, setLanguage] = useState<IndicLanguage>("en");
  const [classification, setClassification] = useState(initialClassification);
  const [classificationBusy, setClassificationBusy] = useState(true);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [evidence, setEvidence] = useState<RetrievedEvidence[]>([]);
  const [askBusy, setAskBusy] = useState(false);
  const [escalation, setEscalation] = useState<EscalationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paidConsent, setPaidConsent] = useState(false);
  const [sessionId] = useState(() => crypto.randomUUID());

  const moveClassification = useCallback(async (trail: TrailStep[], answerIndex: number | null) => {
    setClassificationBusy(true); setError(null);
    try {
      const next = await api<ClassificationState>("/classify/next", { session_id: sessionId, trail, answer_index: answerIndex });
      setClassification(next);
    } catch { setError(t("classificationError")); } finally { setClassificationBusy(false); }
  }, [sessionId]);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const next = await api<ClassificationState>("/classify/next", { session_id: sessionId, trail: [], answer_index: null });
        if (active) setClassification(next);
      } catch {
        if (active) setError(t("classificationError"));
      } finally {
        if (active) setClassificationBusy(false);
      }
    };
    void load();
    return () => { active = false; };
  }, [sessionId]);

  const submitQuestion = async () => {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || askBusy) return;
    setAskBusy(true); setError(null); setAnswer(null); setEscalation(null);
    try {
      const [retrieved, response] = await Promise.all([
        api<RetrieveResponse>("/retrieve", { query: trimmedQuestion, jurisdiction, language }),
        api<AskResponse>("/ask", { query: trimmedQuestion, jurisdiction, language, session_id: sessionId }),
      ]);
      setEvidence(retrieved.results); setAnswer(response);
    } catch { setError(t("errorGeneric")); } finally { setAskBusy(false); }
  };

  const askAboutClassification = () => {
    if (classification.result) setQuestion(`How does the ${classification.result.category} pathway apply to this product?`);
  };

  const escalate = async () => {
    if (!question.trim() || !answer?.abstain) return;
    setAskBusy(true);
    try {
      const response = await api<EscalationResponse>("/escalate", { session_id: sessionId, question, reason: "abstained-answer", priority: "normal" });
      setEscalation(response);
    } catch { setError(t("errorGeneric")); } finally { setAskBusy(false); }
  };

  return (
    <main className="app-shell">
      <div className="disclaimer-banner" role="note"><span className="disclaimer-mark" aria-hidden="true">!</span><span>{t("disclaimer")}</span></div>
      <header className="topbar">
        <div className="brand-lockup"><span className="brand-mark" aria-hidden="true">I</span><div><p className="brand-name">{t("brand")}</p><p className="brand-subtitle">{t("productLabel")}</p></div></div>
        <div className="topbar-meta"><span className="live-dot" aria-hidden="true" /><span>{t("session")}: {sessionId.slice(0, 8)}</span></div>
      </header>

      <section className="workspace-heading" aria-labelledby="workspace-title">
        <div><p className="eyebrow">{t("workspaceEyebrow")}</p><h1 id="workspace-title">{t("workspaceTitle")}</h1></div>
        <div className="query-controls"><fieldset className="jurisdiction-control"><legend>{t("jurisdiction")}</legend><div className="segmented-control" role="radiogroup" aria-label={t("jurisdiction")}>
          {(["IN", "INTL", "BOTH"] as Jurisdiction[]).map((value) => <label className={jurisdiction === value ? "segment active" : "segment"} key={value}><input type="radio" name="jurisdiction" value={value} checked={jurisdiction === value} onChange={() => setJurisdiction(value)} />{value === "IN" ? t("jurisdictionIn") : value === "INTL" ? t("jurisdictionIntl") : t("jurisdictionBoth")}</label>)}
        </div></fieldset><label className="language-control"><span>{t("language")}</span><select value={language} onChange={(event) => setLanguage(event.target.value as IndicLanguage)}>{languages.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select></label></div>
      </section>
      {error && <div className="error-strip" role="alert">{error}</div>}

      <section className="paid-consent" aria-label="Paid source consent">
        <label><input type="checkbox" checked={paidConsent} onChange={(event) => setPaidConsent(event.target.checked)} /> I explicitly consent to sending my paid-source query to the selected provider and recording the exact query for audit.</label>
        <button className="outline-button" disabled={!paidConsent} title={paidConsent ? "Paid-source consent accepted" : "Accept consent before paid-source search"}>Paid-source search</button>
        <p>Paid-source search controls remain disabled until this consent is accepted.</p>
      </section>

      <div className="workspace-grid">
        <aside className="classification-panel" aria-labelledby="classification-title">
          <PanelHeading eyebrow={t("classificationEyebrow")} title={t("classification")} index="01" />
          <p className="panel-intro">{t("classificationIntro")}</p>
          <div className="tree-track" aria-hidden="true"><span className={classification.complete ? "track-node complete" : "track-node current"} /><span className="track-line" /><span className="track-node" /></div>
          <div className="classification-content">
            {classificationBusy && <p className="muted-text">{t("classificationLoading")}</p>}
            {!classificationBusy && classification.question && <><p className="question-label">{t("options")}</p><h3>{classification.question}</h3><div className="option-list">{classification.options.map((option, index) => <button className="option-button" key={option} onClick={() => void moveClassification(classification.trail, index)} disabled={classificationBusy}><span className="option-number">{String(index + 1).padStart(2, "0")}</span><span>{option}</span><span className="option-arrow" aria-hidden="true">↗</span></button>)}</div></>}
            {!classificationBusy && classification.result && <div className="classification-result"><p className="question-label">{t("classificationComplete")}</p><h3>{classification.result.category}</h3><ResultField label={t("regulatoryPath")} value={classification.result.regulatory_path} /><ResultField label={t("ipPosture")} value={classification.result.ip_posture} /><ResultField label={t("absNote")} value={classification.result.abs_note} /><button className="text-action" onClick={askAboutClassification}>{t("askAboutClassification")} <span aria-hidden="true">→</span></button></div>}
          </div>
        </aside>

        <section className="qa-panel" aria-labelledby="qa-title">
          <PanelHeading eyebrow={t("qaEyebrow")} title={t("qa")} index="02" />
          <p className="panel-intro">{t("qaIntro")}</p>
          <div className="question-composer"><label htmlFor="question-input" className="sr-only">{t("qaPlaceholder")}</label><textarea id="question-input" value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") void submitQuestion(); }} placeholder={t("qaPlaceholder")} rows={4} /><div className="composer-footer"><span className="composer-hint">{jurisdiction === "BOTH" ? t("bothShort") : jurisdiction}</span><button className="primary-button" onClick={() => void submitQuestion()} disabled={askBusy || !question.trim()}>{askBusy ? t("qaWorking") : t("qaSubmit")} <span aria-hidden="true">↗</span></button></div></div>
          <div className="answer-area" aria-live="polite">
            {!answer && !askBusy && <div className="empty-state"><span className="empty-rule" />{t("qaEmpty")}</div>}
            {askBusy && <div className="empty-state"><span className="loading-pulse" />{t("qaWorking")}</div>}
            {answer && !answer.abstain && <article className="answer-block"><div className="answer-header"><span className="answer-kicker">{answer.mode === "split" ? t("splitLabel") : t("result")}</span>{answer.confidence && <span className={`confidence-badge ${answer.confidence}`}>{t(answer.confidence)}</span>}</div>{answer.mode === "split" && answer.sections ? <div className="split-answer">{answer.sections.map((section, index) => <section className="jurisdiction-section" key={`${section.jurisdiction}-${index}`}><p className="section-marker">{section.jurisdiction ?? `${index + 1}`}</p><h3>{section.title ?? section.jurisdiction ?? ""}</h3><p><InlineCitations text={section.text ?? section.answer ?? ""} /></p></section>)}</div> : <p className="answer-copy"><InlineCitations text={answer.answer ?? ""} /></p>}<div className="answer-citations"><span className="question-label">{t("citations")}</span>{answer.citations.map((citation) => <span className="citation-chip" key={citation}>{citation}</span>)}</div></article>}
            {answer?.abstain && <article className="abstain-block"><div className="abstain-symbol" aria-hidden="true">—</div><div><p className="answer-kicker">{t("abstained")}</p><p>{t("abstainedReason")}</p>{!escalation ? <button className="outline-button" onClick={() => void escalate()} disabled={askBusy}>{askBusy ? t("escalating") : t("escalate")} <span aria-hidden="true">→</span></button> : <p className="success-note">{t("escalated")} · {t("trackingId")}: {escalation.tracking_id}</p>}</div></article>}
          </div>
        </section>

        <aside className="evidence-panel" aria-labelledby="evidence-title">
          <PanelHeading eyebrow={t("evidence")} title={t("citations")} index="03" /><p className="panel-intro">{t("evidenceIntro")}</p>
          {evidence.length === 0 ? <p className="muted-text">{t("noEvidence")}</p> : <ol className="evidence-list">{evidence.map((item, index) => <li key={item.chunk_id} className="evidence-item"><span className="evidence-count">{String(index + 1).padStart(2, "0")}</span><div><p className="evidence-id">{item.chunk_id}</p><p className="evidence-source">{item.instrument} · {item.section}</p><p className="evidence-excerpt">{item.chunk_text}</p></div></li>)}</ol>}
        </aside>
      </div>
    </main>
  );
}

function PanelHeading({ eyebrow, title, index }: { eyebrow: string; title: string; index: string }) {
  return <div className="panel-heading"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div><span className="panel-index">{index}</span></div>;
}

function ResultField({ label, value }: { label: string; value: string }) {
  return <div className="result-field"><p>{label}</p><span>{value}</span></div>;
}

export default App;
