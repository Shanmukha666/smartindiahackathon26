import { useCallback, useEffect, useState } from "react";
import { postApi } from "./api/client";
import { InlineCitations, PanelHeading, ResultField } from "./components/atoms";
import { t } from "./i18n/resources";
import type { AskResponse, ClassificationState, DevSessionResponse, EscalationResponse, IndicLanguage, Jurisdiction, PaidSourceResponse, RetrievedEvidence, SpeechResponse, TrailStep } from "./types";

const languages: { code: IndicLanguage; label: string }[] = [
  { code: "en", label: "English" }, { code: "hi", label: "Hindi" }, { code: "bn", label: "Bengali" }, { code: "gu", label: "Gujarati" },
  { code: "kn", label: "Kannada" }, { code: "ml", label: "Malayalam" }, { code: "mr", label: "Marathi" }, { code: "or", label: "Odia" },
  { code: "pa", label: "Punjabi" }, { code: "ta", label: "Tamil" }, { code: "te", label: "Telugu" }, { code: "ur", label: "Urdu" },
];

const initialClassification: ClassificationState = { complete: false, question: null, options: [], trail: [], result: null };

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
  const [devToken, setDevToken] = useState<string | null>(null);
  const [paidResults, setPaidResults] = useState<PaidSourceResponse["results"]>([]);
  const [sessionId] = useState(() => crypto.randomUUID());

  const moveClassification = useCallback(async (trail: TrailStep[], answerIndex: number | null) => {
    setClassificationBusy(true); setError(null);
    try {
      const next = await postApi<ClassificationState>("/classify/next", { session_id: sessionId, trail, answer_index: answerIndex });
      setClassification(next);
    } catch { setError(t("classificationError")); } finally { setClassificationBusy(false); }
  }, [sessionId]);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const next = await postApi<ClassificationState>("/classify/next", { session_id: sessionId, trail: [], answer_index: null });
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

  useEffect(() => {
    void postApi<DevSessionResponse>("/auth/dev-session", {}).then((session) => setDevToken(session.access_token)).catch(() => undefined);
  }, []);

  const submitQuestion = async () => {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || askBusy) return;
    setAskBusy(true); setError(null); setAnswer(null); setEscalation(null);
    try {
      const response = await postApi<AskResponse>("/ask", { query: trimmedQuestion, jurisdiction, language, session_id: sessionId }, devToken ?? undefined);
      setEvidence(response.evidence); setAnswer(response);
    } catch { setError(t("errorGeneric")); } finally { setAskBusy(false); }
  };

  const askAboutClassification = () => {
    if (classification.result) setQuestion(`How does the ${classification.result.category} pathway apply to this product?`);
  };

  const escalate = async () => {
    if (!question.trim() || !answer?.abstain) return;
    setAskBusy(true);
    try {
      const response = await postApi<EscalationResponse>("/escalate", { session_id: sessionId, question, reason: "abstained-answer", priority: "normal" }, devToken ?? undefined);
      setEscalation(response);
    } catch { setError(t("errorGeneric")); } finally { setAskBusy(false); }
  };

  const searchPaidSources = async () => {
    if (!paidConsent || !question.trim()) return;
    setError(null); setPaidResults([]);
    try {
      const response = await postApi<PaidSourceResponse>("/paid-sources/stub/search", { query: question.trim(), consent_accepted: true }, devToken ?? undefined);
      setPaidResults(response.results);
    } catch { setError("Paid-source search is unavailable. Start the local demo session or configure an approved provider."); }
  };

  const listenToAnswer = async () => {
    const text = answer?.answer ?? answer?.sections?.map((section) => section.text ?? section.answer ?? "").join(" ");
    if (!text) return;
    try {
      const response = await postApi<SpeechResponse>("/speech/synthesize", { text, language });
      const bytes = Uint8Array.from(atob(response.audio_base64), (character) => character.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: response.audio_format }));
      const audio = new Audio(url); audio.onended = () => URL.revokeObjectURL(url); await audio.play();
    } catch { setError("Speech playback is unavailable for this language or environment."); }
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
        </div></fieldset><label className="language-control"><span>{t("language")}</span><select value={language} onChange={(event) => setLanguage(event.target.value as IndicLanguage)} aria-describedby="language-help">{languages.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select><span id="language-help" className="language-help">{t("languageHelp")}</span></label></div>
      </section>
      {error && <div className="error-strip" role="alert">{error}</div>}

      <section className="paid-consent" aria-label="Paid source consent">
        <label><input type="checkbox" checked={paidConsent} onChange={(event) => setPaidConsent(event.target.checked)} /> I explicitly consent to sending my paid-source query to the selected provider and recording the exact query for audit.</label>
        <button className="outline-button" onClick={() => void searchPaidSources()} disabled={!paidConsent || !question.trim()} title={paidConsent ? "Search the current question" : "Accept consent before paid-source search"}>Paid-source search</button>
        <p>{!paidConsent ? "Paid-source search controls remain disabled until this consent is accepted." : !question.trim() ? "Enter a question before searching." : "The selected provider receives this query and the consent is audited."}</p>
        {paidResults.length > 0 && <ol className="paid-results">{paidResults.map((result, index) => <li key={`${result.title ?? "result"}-${index}`}><strong>{result.title ?? "Result"}</strong>{result.summary && <span>{result.summary}</span>}{result.url && <a href={result.url} target="_blank" rel="noreferrer">Open source</a>}</li>)}</ol>}
      </section>

      <div className="workspace-grid">
        <aside className="classification-panel" aria-labelledby="classification-title">
          <PanelHeading eyebrow={t("classificationEyebrow")} title={t("classification")} index="01" />
          <p className="panel-intro">{t("classificationIntro")}</p>
          <div className="tree-track" aria-hidden="true"><span className={classification.complete ? "track-node complete" : "track-node current"} /><span className="track-line" /><span className="track-node" /></div>
          <div className="classification-content">
            {classificationBusy && <p className="muted-text">{t("classificationLoading")}</p>}
            {!classificationBusy && classification.question && <><p className="question-label">{t("options")}</p><h3>{classification.question}</h3><div className="option-list">{classification.options.map((option, index) => <button className="option-button" key={option} onClick={() => void moveClassification(classification.trail, index)} disabled={classificationBusy}><span className="option-number">{String(index + 1).padStart(2, "0")}</span><span>{option}</span><span className="option-arrow" aria-hidden="true">↗</span></button>)}</div></>}
            {!classificationBusy && classification.result && <div className="classification-result"><p className="question-label">{t("classificationComplete")}</p><h3>{classification.result.category}</h3><ResultField label={t("regulatoryPath")} value={classification.result.regulatory_path} /><ResultField label={t("ipPosture")} value={classification.result.ip_posture} /><ResultField label={t("absNote")} value={classification.result.abs_note} /><div className="result-field"><p>{t("ipRoutes")}</p><ul className="ip-route-list">{classification.result.recommended_ip_routes.map((route) => <li key={route}>{route}</li>)}</ul></div>{classification.result.tkdl_prior_art_guidance && <div className="result-field"><p>{t("tkdlCheck")}</p><span>{classification.result.tkdl_prior_art_guidance}</span><a className="source-link" href="https://www.tkdl.res.in/tkdl/langdefault/common/Home.asp?GL=Eng" target="_blank" rel="noreferrer">{t("tkdlLink")}</a></div>}<button className="text-action" onClick={askAboutClassification}>{t("askAboutClassification")} <span aria-hidden="true">→</span></button></div>}
            {!classificationBusy && classification.result && <div className="result-field"><p>{t("absChecklist")}</p><ul className="ip-route-list">{classification.result.abs_actions.map((action) => <li key={action}>{action}</li>)}</ul></div>}
            {!classificationBusy && classification.result && <div className="result-field official-sources"><p>{t("officialSources")}</p><span>{t("officialSourcesNote")}</span><ul className="official-source-list">{classification.result.official_sources.map((source) => <li key={source.url}><a className="source-link" href={source.url} target="_blank" rel="noreferrer">{source.label}</a><small>{source.description}</small></li>)}</ul></div>}
          </div>
        </aside>

        <section className="qa-panel" aria-labelledby="qa-title">
          <PanelHeading eyebrow={t("qaEyebrow")} title={t("qa")} index="02" />
          <p className="panel-intro">{t("qaIntro")}</p>
          <div className="question-composer"><label htmlFor="question-input" className="sr-only">{t("qaPlaceholder")}</label><textarea id="question-input" value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") void submitQuestion(); }} placeholder={t("qaPlaceholder")} rows={4} /><div className="composer-footer"><span className="composer-hint">{jurisdiction === "BOTH" ? t("bothShort") : jurisdiction}</span><button className="primary-button" onClick={() => void submitQuestion()} disabled={askBusy || !question.trim()}>{askBusy ? t("qaWorking") : t("qaSubmit")} <span aria-hidden="true">↗</span></button></div></div>
          <div className="answer-area" aria-live="polite">
            {!answer && !askBusy && <div className="empty-state"><span className="empty-rule" />{t("qaEmpty")}</div>}
            {askBusy && <div className="empty-state"><span className="loading-pulse" />{t("qaWorking")}</div>}
            {answer && !answer.abstain && <article className="answer-block"><div className="answer-header"><span className="answer-kicker">{answer.mode === "split" ? t("splitLabel") : t("result")}</span>{answer.confidence && <span className={`confidence-badge ${answer.confidence}`}>{t(answer.confidence)}</span>}<button className="text-action" onClick={() => void listenToAnswer()}>Listen</button></div>{answer.mode === "split" && answer.sections ? <div className="split-answer">{answer.sections.map((section, index) => <section className="jurisdiction-section" key={`${section.jurisdiction}-${index}`}><p className="section-marker">{section.jurisdiction ?? `${index + 1}`}</p><h3>{section.title ?? section.jurisdiction ?? ""}</h3><p><InlineCitations text={section.text ?? section.answer ?? ""} /></p></section>)}</div> : <p className="answer-copy"><InlineCitations text={answer.answer ?? ""} /></p>}<div className="answer-citations"><span className="question-label">{t("citations")}</span>{answer.citations.map((citation) => <span className="citation-chip" key={citation}>{citation}</span>)}</div></article>}
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

export default App;
