import { useCallback, useEffect, useState } from "react";
import { postApi } from "./api/client";
import { InlineCitations } from "./components/atoms";
import { t } from "./i18n/resources";
import type {
  AskResponse,
  ClassificationState,
  DevSessionResponse,
  EscalationResponse,
  IndicLanguage,
  IngestResponse,
  Jurisdiction,
  PaidSourceResponse,
  RetrievedEvidence,
  SpeechResponse,
  TrailStep,
} from "./types";

const languages: { code: IndicLanguage; label: string }[] = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी (Hindi)" },
  { code: "bn", label: "বাংলা (Bengali)" },
  { code: "gu", label: "ગુજરાતી (Gujarati)" },
  { code: "kn", label: "ಕನ್ನಡ (Kannada)" },
  { code: "ml", label: "മലയാളം (Malayalam)" },
  { code: "mr", label: "मराठी (Marathi)" },
  { code: "or", label: "ଓଡ଼ିଆ (Odia)" },
  { code: "pa", label: "ਪੰਜਾਬੀ (Punjabi)" },
  { code: "ta", label: "தமிழ் (Tamil)" },
  { code: "te", label: "తెలుగు (Telugu)" },
  { code: "ur", label: "اردو (Urdu)" },
];

const initialClassification: ClassificationState = {
  complete: false,
  question: null,
  options: [],
  trail: [],
  result: null,
};

type ActiveTab =
  | "ai-research-assistant"
  | "formulation-classifier"
  | "document-ingestion"
  | "legal-knowledge-graph"
  | "human-review-escalations";

export default function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("ai-research-assistant");
  const [jurisdiction, setJurisdiction] = useState<Jurisdiction>("BOTH");
  const [language, setLanguage] = useState<IndicLanguage>("en");
  const [classification, setClassification] = useState<ClassificationState>(initialClassification);
  const [classificationBusy, setClassificationBusy] = useState(true);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [evidence, setEvidence] = useState<RetrievedEvidence[]>([]);
  const [activeCitationId, setActiveCitationId] = useState<string | null>(null);
  const [isEvidenceDrawerOpen, setIsEvidenceDrawerOpen] = useState(true);
  const [askBusy, setAskBusy] = useState(false);
  const [escalation, setEscalation] = useState<EscalationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paidConsent, setPaidConsent] = useState(false);
  const [devToken, setDevToken] = useState<string | null>(null);
  const [paidResults, setPaidResults] = useState<PaidSourceResponse["results"]>([]);
  const [sessionId] = useState(() => crypto.randomUUID());

  // Ingestion Hub state
  const [ingestMode, setIngestMode] = useState<"gdrive" | "url" | "upload">("url");
  const [ingestUrl, setIngestUrl] = useState("https://ayush.gov.in/");
  const [ingestGdriveId, setIngestGdriveId] = useState("1mFlOji63T0ETs5XwDsdyAkFucB9Zxgsh");
  const [ingestFilename, setIngestFilename] = useState("ayush_regulation_2026.txt");
  const [ingestContent, setIngestContent] = useState("Section 1. Guidelines for AYUSH Patent Examination\nTraditional Knowledge Digital Library access must be consulted.");
  const [ingestBusy, setIngestBusy] = useState(false);
  const [ingestResult, setIngestResult] = useState<IngestResponse | null>(null);
  const [ingestError, setIngestError] = useState<string | null>(null);

  const moveClassification = useCallback(
    async (trail: TrailStep[], answerIndex: number | null) => {
      setClassificationBusy(true);
      setError(null);
      try {
        const next = await postApi<ClassificationState>("/classify/next", {
          session_id: sessionId,
          trail,
          answer_index: answerIndex,
        });
        setClassification(next);
      } catch {
        setError(t("classificationError"));
      } finally {
        setClassificationBusy(false);
      }
    },
    [sessionId]
  );

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const next = await postApi<ClassificationState>("/classify/next", {
          session_id: sessionId,
          trail: [],
          answer_index: null,
        });
        if (active) setClassification(next);
      } catch {
        if (active) setError(t("classificationError"));
      } finally {
        if (active) setClassificationBusy(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [sessionId]);

  useEffect(() => {
    void postApi<DevSessionResponse>("/auth/dev-session", {})
      .then((session) => setDevToken(session.access_token))
      .catch(() => undefined);
  }, []);

  const submitQuestion = async () => {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || askBusy) return;
    setAskBusy(true);
    setError(null);
    setAnswer(null);
    setEscalation(null);
    try {
      const response = await postApi<AskResponse>(
        "/ask",
        { query: trimmedQuestion, jurisdiction, language, session_id: sessionId },
        devToken ?? undefined
      );
      setEvidence(response.evidence);
      setAnswer(response);
      if (response.evidence.length > 0) {
        setIsEvidenceDrawerOpen(true);
      }
    } catch {
      setError(t("errorGeneric"));
    } finally {
      setAskBusy(false);
    }
  };

  const askAboutClassification = () => {
    if (classification.result) {
      setQuestion(`How does the ${classification.result.category} pathway apply to this product under Indian patent law?`);
      setActiveTab("ai-research-assistant");
    }
  };

  const escalate = async () => {
    if (!question.trim() || !answer?.abstain) return;
    setAskBusy(true);
    try {
      const response = await postApi<EscalationResponse>(
        "/escalate",
        { session_id: sessionId, question, reason: "abstained-answer", priority: "normal" },
        devToken ?? undefined
      );
      setEscalation(response);
    } catch {
      setError(t("errorGeneric"));
    } finally {
      setAskBusy(false);
    }
  };

  const searchPaidSources = async () => {
    if (!paidConsent || !question.trim()) return;
    setError(null);
    setPaidResults([]);
    try {
      const response = await postApi<PaidSourceResponse>(
        "/paid-sources/stub/search",
        { query: question.trim(), consent_accepted: true },
        devToken ?? undefined
      );
      setPaidResults(response.results);
    } catch {
      setError("Paid-source search is unavailable. Start the local demo session or configure an approved provider.");
    }
  };

  const listenToAnswer = async () => {
    const text =
      answer?.answer ??
      answer?.sections?.map((section) => section.text ?? section.answer ?? "").join(" ");
    if (!text) return;
    try {
      const response = await postApi<SpeechResponse>("/speech/synthesize", { text, language });
      const bytes = Uint8Array.from(atob(response.audio_base64), (character) => character.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: response.audio_format }));
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
    } catch {
      setError("Speech playback is unavailable for this language or environment.");
    }
  };

  const handleIngest = async () => {
    setIngestBusy(true);
    setIngestError(null);
    setIngestResult(null);
    try {
      let res: IngestResponse;
      if (ingestMode === "gdrive") {
        res = await postApi<IngestResponse>(
          "/ingest/gdrive",
          { file_id: ingestGdriveId, jurisdiction: jurisdiction === "INTL" ? "INTL" : "IN" },
          devToken ?? undefined
        );
      } else if (ingestMode === "url") {
        res = await postApi<IngestResponse>(
          "/ingest/url",
          { url: ingestUrl, jurisdiction: jurisdiction === "INTL" ? "INTL" : "IN" },
          devToken ?? undefined
        );
      } else {
        res = await postApi<IngestResponse>(
          "/ingest/upload",
          { filename: ingestFilename, content: ingestContent, jurisdiction: jurisdiction === "INTL" ? "INTL" : "IN" },
          devToken ?? undefined
        );
      }
      setIngestResult(res);
    } catch (err: unknown) {
      setIngestError(err instanceof Error ? err.message : "Ingestion failed. Ensure provider credentials are configured.");
    } finally {
      setIngestBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-on-surface antialiased font-sans">
      {/* Top Fixed Header */}
      <header className="fixed top-0 left-0 right-0 h-16 bg-surface-container-lowest/95 backdrop-blur-md z-50 border-b border-surface-container shadow-[0_1px_8px_rgba(0,0,0,0.04)]">
        <div className="h-16 w-full px-4 sm:px-6 flex items-center justify-between gap-4">
          {/* Brand & Emblem */}
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-primary flex items-center justify-center text-on-primary font-display font-bold text-lg shadow-sm">
              <span className="material-symbols-outlined text-2xl text-primary-fixed">local_florist</span>
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <span className="font-display font-bold text-base text-primary tracking-tight">
                  IP-SAKTI Sahayak
                </span>
                <span className="px-1.5 py-0.5 rounded bg-primary-container text-on-primary font-mono text-[10px] font-bold">
                  SIH 26045
                </span>
              </div>
              <span className="text-[11px] text-on-surface-variant leading-none hidden sm:inline">
                AYUSH IPR &amp; Regulatory Intelligence Assistant
              </span>
            </div>
          </div>

          {/* Center Badges & Controls */}
          <div className="flex items-center gap-3">
            {/* Jurisdiction Segmented Buttons */}
            <div className="hidden lg:flex items-center bg-surface-container-low rounded-xl p-1 border border-surface-container">
              {(["IN", "INTL", "BOTH"] as Jurisdiction[]).map((val) => (
                <button
                  key={val}
                  type="button"
                  onClick={() => setJurisdiction(val)}
                  className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${
                    jurisdiction === val
                      ? "bg-primary text-on-primary shadow-sm"
                      : "text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  {val === "IN" ? "India (IN)" : val === "INTL" ? "International" : "Both"}
                </button>
              ))}
            </div>

            {/* Language Selector */}
            <div className="flex items-center gap-1.5 bg-surface-container-low px-2.5 py-1.5 rounded-xl border border-surface-container">
              <span className="material-symbols-outlined text-base text-tertiary">translate</span>
              <select
                aria-label="Select Language"
                value={language}
                onChange={(e) => setLanguage(e.target.value as IndicLanguage)}
                className="bg-transparent text-xs font-medium text-on-surface outline-none cursor-pointer pr-1"
              >
                {languages.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Live Engine Status */}
            <div className="hidden xl:flex items-center gap-2 px-3 py-1.5 bg-surface-container-low rounded-xl border border-surface-container text-xs">
              <span className="w-2 h-2 rounded-full bg-surface-tint animate-pulse" />
              <span className="font-mono text-on-surface font-medium text-[11px]">pgvector + Voyage</span>
              <span className="text-outline-variant font-mono">|</span>
              <span className="material-symbols-outlined text-sm text-surface-tint">dns</span>
              <span className="text-on-surface-variant text-[11px]">RAG Active</span>
            </div>

            {/* Reviewer Profile Badge */}
            <div className="flex items-center gap-2 px-2.5 py-1 rounded-xl bg-surface-container-low border border-surface-container">
              <div className="w-7 h-7 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center font-bold text-xs">
                SD
              </div>
              <div className="hidden sm:flex flex-col text-left">
                <span className="text-xs font-semibold text-on-surface leading-tight">Dr. S. Dasari</span>
                <span className="text-[10px] font-medium text-secondary leading-tight">Legal Reviewer</span>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Left Sidebar Navigation */}
      <aside className="fixed left-0 top-16 bottom-0 w-64 bg-surface-container-lowest border-r border-surface-container z-40 flex flex-col justify-between shadow-[0_1px_8px_rgba(0,0,0,0.04)]">
        <div className="flex-1 overflow-y-auto py-4 px-3">
          <div className="px-3 mb-2 text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">
            Intelligence Suites
          </div>
          <nav className="space-y-1 mb-6">
            <button
              type="button"
              onClick={() => setActiveTab("ai-research-assistant")}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl transition-all text-left ${
                activeTab === "ai-research-assistant"
                  ? "bg-primary-container text-on-primary shadow-sm font-semibold"
                  : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span className="material-symbols-outlined text-[20px]">neurology</span>
                <span className="text-xs font-semibold">AI Assistant</span>
              </div>
              <span className="px-1.5 py-0.5 rounded bg-primary-fixed text-on-primary-fixed font-mono text-[10px] font-bold">
                RAG
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("formulation-classifier")}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl transition-all text-left ${
                activeTab === "formulation-classifier"
                  ? "bg-primary-container text-on-primary shadow-sm font-semibold"
                  : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span className="material-symbols-outlined text-[20px]">account_tree</span>
                <span className="text-xs font-semibold">Formulation Classifier</span>
              </div>
              <span className="px-1.5 py-0.5 rounded bg-surface-container text-on-surface font-mono text-[10px]">
                Tree
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("document-ingestion")}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl transition-all text-left ${
                activeTab === "document-ingestion"
                  ? "bg-primary-container text-on-primary shadow-sm font-semibold"
                  : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span className="material-symbols-outlined text-[20px]">cloud_sync</span>
                <span className="text-xs font-semibold">Ingestion &amp; Scraping</span>
              </div>
              <span className="px-1.5 py-0.5 rounded bg-secondary-fixed text-on-secondary-fixed font-mono text-[10px] font-bold">
                n8n
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("legal-knowledge-graph")}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl transition-all text-left ${
                activeTab === "legal-knowledge-graph"
                  ? "bg-primary-container text-on-primary shadow-sm font-semibold"
                  : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span className="material-symbols-outlined text-[20px]">menu_book</span>
                <span className="text-xs font-semibold">Statutory Corpus</span>
              </div>
              <span className="px-1.5 py-0.5 rounded bg-surface-container text-on-surface font-mono text-[10px]">
                5 Acts
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("human-review-escalations")}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl transition-all text-left ${
                activeTab === "human-review-escalations"
                  ? "bg-primary-container text-on-primary shadow-sm font-semibold"
                  : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span className="material-symbols-outlined text-[20px]">gavel</span>
                <span className="text-xs font-semibold">Review &amp; Escalations</span>
              </div>
              {escalation ? (
                <span className="px-1.5 py-0.5 rounded-full bg-secondary text-on-secondary text-[10px] font-bold">
                  1
                </span>
              ) : null}
            </button>
          </nav>

          <div className="px-3 mb-2 text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">
            External Legal Portals
          </div>
          <div className="space-y-1">
            <a
              href="https://www.tkdl.res.in/tkdl/langdefault/common/Home.asp?GL=Eng"
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-between px-3 py-2 rounded-xl text-xs text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[16px]">library_books</span>
                <span>TKDL Access</span>
              </div>
              <span className="material-symbols-outlined text-xs">open_in_new</span>
            </a>
            <a
              href="https://ipindia.gov.in/pages/e-services"
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-between px-3 py-2 rounded-xl text-xs text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[16px]">verified</span>
                <span>IP India E-Services</span>
              </div>
              <span className="material-symbols-outlined text-xs">open_in_new</span>
            </a>
            <a
              href="https://patentscope.wipo.int/search/en/search.jsf"
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-between px-3 py-2 rounded-xl text-xs text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[16px]">public</span>
                <span>WIPO PATENTSCOPE</span>
              </div>
              <span className="material-symbols-outlined text-xs">open_in_new</span>
            </a>
          </div>
        </div>

        {/* Compliance Notice */}
        <div className="p-3 m-3 bg-surface-container-low rounded-xl border border-surface-container">
          <div className="flex items-start gap-2">
            <span className="material-symbols-outlined text-base text-secondary mt-0.5">shield</span>
            <div>
              <div className="text-[10px] font-bold text-on-surface uppercase tracking-wider">Compliance Notice</div>
              <p className="text-[11px] text-on-surface-variant mt-0.5 leading-snug">
                Regulatory assistive system. Information only, not legal advice.
              </p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className={`pl-64 pt-16 transition-all duration-300 ${isEvidenceDrawerOpen && evidence.length > 0 ? "xl:pr-80" : ""}`}>
        <main className="w-full min-h-[calc(100vh-4rem)] p-4 sm:p-6 max-w-7xl mx-auto">
          {/* Error Banner */}
          {error && (
            <div className="mb-4 p-3 rounded-xl bg-error-container text-on-error-container text-xs flex items-center gap-2">
              <span className="material-symbols-outlined text-base">error</span>
              <span>{error}</span>
            </div>
          )}

          {/* TAB 1: AI Research Assistant */}
          {activeTab === "ai-research-assistant" && (
            <div className="flex flex-col gap-5">
              {/* Active Formulation Diagnostic Banner */}
              {classification.question && (
                <div className="w-full p-3 rounded-xl bg-surface-container-low border border-surface-container flex flex-wrap items-center justify-between gap-2 shadow-sm">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-base text-surface-tint">account_tree</span>
                    <span className="text-xs font-bold text-primary">Formulation Triage:</span>
                    <span className="text-xs font-medium text-on-surface">{classification.question}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {classification.options.map((opt, i) => (
                      <button
                        key={i}
                        type="button"
                        onClick={() => void moveClassification(classification.trail, i)}
                        disabled={classificationBusy}
                        className="px-2.5 py-1 rounded-lg bg-surface-container-lowest border border-surface-container hover:bg-primary-container hover:text-on-primary hover:border-transparent text-xs font-semibold transition-all cursor-pointer shadow-xs"
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Context Header Ribbon */}
              <div className="w-full bg-surface-container-lowest rounded-xl border border-surface-container p-4 shadow-sm flex flex-wrap items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-surface-tint" />
                    <h1 className="font-display font-bold text-lg text-primary">
                      AYUSH Grounded Legal Q&amp;A Assistant
                    </h1>
                    <span className="px-2 py-0.5 rounded bg-surface-container text-on-surface-variant font-mono text-[10px]">
                      Jurisdiction: {jurisdiction}
                    </span>
                  </div>
                  <p className="text-xs text-on-surface-variant mt-0.5">
                    Autonomous regulatory triage engine grounded in Indian Patent Act (1970), NBA directives &amp; TKDL catalogs.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-secondary-fixed text-on-secondary-fixed text-[11px] font-semibold">
                    <span className="material-symbols-outlined text-sm">warning</span>
                    Patents Act §3(p)
                  </span>
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-primary-fixed text-on-primary-fixed text-[11px] font-semibold">
                    <span className="material-symbols-outlined text-sm">eco</span>
                    Biological Diversity Act
                  </span>
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-tertiary-fixed text-on-tertiary-fixed text-[11px] font-semibold">
                    <span className="material-symbols-outlined text-sm">menu_book</span>
                    TKDL Prior Art
                  </span>
                </div>
              </div>

              {/* Question Input Card */}
              <div className="bg-surface-container-lowest rounded-xl border border-surface-container shadow-sm p-4">
                <label htmlFor="question-input" className="block text-xs font-bold text-on-surface uppercase tracking-wider mb-2">
                  Enter Regulatory Query or Patent Question
                </label>
                <textarea
                  id="question-input"
                  role="textbox"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => {
                    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void submitQuestion();
                  }}
                  placeholder="e.g. Can I patent an enhanced bioavailable formulation of Curcuma longa (Turmeric) and Piperine with novel liposomal encapsulation?"
                  rows={3}
                  className="w-full p-3 rounded-lg bg-surface-container-low border border-surface-container text-sm text-on-surface placeholder:text-outline focus:outline-none focus:ring-2 focus:ring-primary leading-relaxed resize-y"
                />

                <div className="mt-3 flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-surface-container">
                  <div className="flex items-center gap-2 text-xs text-on-surface-variant">
                    <span className="material-symbols-outlined text-base text-tertiary">keyboard</span>
                    <span>Press <kbd className="px-1.5 py-0.5 rounded bg-surface-container font-mono text-[10px]">Ctrl+Enter</kbd> to submit</span>
                  </div>

                  <div className="flex items-center gap-2">
                    {answer && (
                      <button
                        type="button"
                        onClick={() => void listenToAnswer()}
                        className="px-3 py-1.5 rounded-lg border border-surface-container text-xs font-semibold text-primary hover:bg-surface-container flex items-center gap-1.5 transition-colors"
                      >
                        <span className="material-symbols-outlined text-base text-tertiary">volume_up</span>
                        <span>Listen</span>
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => void submitQuestion()}
                      disabled={askBusy || !question.trim()}
                      className="px-4 py-1.5 rounded-lg bg-primary hover:bg-primary-container text-on-primary text-xs font-bold transition-all shadow-sm flex items-center gap-1.5 cursor-pointer"
                    >
                      {askBusy ? (
                        <>
                          <span className="w-3 h-3 border-2 border-on-primary border-t-transparent rounded-full animate-spin" />
                          <span>Thinking...</span>
                        </>
                      ) : (
                        <>
                          <span>Ask Sahayak</span>
                          <span className="material-symbols-outlined text-sm">send</span>
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>

              {/* Answer Presentation Card */}
              {answer && !answer.abstain && (
                <div className="bg-surface-container-lowest rounded-xl border border-surface-container shadow-md p-5 relative overflow-hidden">
                  <div className="absolute left-0 top-0 bottom-0 w-1.5 bg-primary" />

                  {/* Header Row */}
                  <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-surface-container">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded-lg bg-primary-container flex items-center justify-center text-on-primary">
                        <span className="material-symbols-outlined text-lg text-primary-fixed">neurology</span>
                      </div>
                      <div>
                        <span className="font-display font-bold text-sm text-primary">
                          IP-SAKTI Regulatory Intelligence Analysis
                        </span>
                        <div className="text-[11px] text-on-surface-variant font-mono">
                          Mode: {answer.mode ?? "single"} • Grounded via statutory corpus
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      {answer.confidence && (
                        <span className={`confidence-badge ${answer.confidence}`}>
                          {answer.confidence} confidence
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => setIsEvidenceDrawerOpen(!isEvidenceDrawerOpen)}
                        className="px-2.5 py-1 rounded bg-surface-container hover:bg-surface-container-high text-on-surface text-xs font-medium flex items-center gap-1 transition-colors"
                      >
                        <span className="material-symbols-outlined text-sm">menu_book</span>
                        <span>{evidence.length} Evidence Chunks</span>
                      </button>
                    </div>
                  </div>

                  {/* Answer Content */}
                  <div className="mt-4 prose prose-sm max-w-none text-on-surface leading-relaxed">
                    {answer.mode === "split" && answer.sections ? (
                      <div className="space-y-4">
                        {answer.sections.map((section, idx) => (
                          <div key={idx} className="p-3.5 rounded-xl bg-surface-container-low border border-surface-container">
                            <span className="text-[11px] font-bold text-secondary uppercase tracking-wider block mb-1">
                              {section.jurisdiction ?? `Section ${idx + 1}`}
                            </span>
                            <h4 className="font-bold text-sm text-on-surface mb-2">
                              {section.title ?? section.jurisdiction}
                            </h4>
                            <p className="text-sm leading-relaxed">
                              <InlineCitations text={section.text ?? section.answer ?? ""} />
                            </p>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-sm sm:text-base leading-relaxed p-2">
                        <InlineCitations text={answer.answer ?? ""} />
                      </div>
                    )}
                  </div>

                  {/* Citations Row */}
                  {answer.citations.length > 0 && (
                    <div className="mt-4 pt-3 border-t border-surface-container flex flex-wrap items-center gap-2">
                      <span className="text-xs font-bold text-on-surface-variant uppercase tracking-wider">
                        Citations:
                      </span>
                      {answer.citations.map((cite) => (
                        <button
                          key={cite}
                          type="button"
                          onClick={() => {
                            setActiveCitationId(cite);
                            setIsEvidenceDrawerOpen(true);
                          }}
                          className={`citation-chip ${activeCitationId === cite ? "ring-2 ring-primary" : ""}`}
                        >
                          <span className="material-symbols-outlined text-[13px] mr-1 text-surface-tint">verified</span>
                          {cite}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Disclaimer banner */}
                  <div className="mt-4 p-2.5 rounded-lg bg-surface-container text-[11px] text-on-surface-variant flex items-center gap-2">
                    <span className="material-symbols-outlined text-sm text-secondary">info</span>
                    <span>{answer.disclaimer}</span>
                  </div>
                </div>
              )}

              {/* Abstention Card with Escalation Trigger */}
              {answer?.abstain && (
                <div className="bg-surface-container-lowest rounded-xl border border-secondary p-5 shadow-md">
                  <div className="flex items-start gap-3">
                    <span className="material-symbols-outlined text-2xl text-secondary">gavel</span>
                    <div className="flex-1">
                      <h3 className="font-display font-bold text-base text-secondary">
                        Statutory Abstention — Insufficient Statutory Evidence
                      </h3>
                      <p className="text-xs text-on-surface-variant mt-1 leading-relaxed">
                        {answer.reason ?? "The retrieved statutory chunks do not provide sufficient grounded basis for this specific query without legal speculation."}
                      </p>

                      <div className="mt-4">
                        {!escalation ? (
                          <button
                            type="button"
                            onClick={() => void escalate()}
                            disabled={askBusy}
                            className="px-4 py-2 rounded-lg bg-secondary text-on-secondary text-xs font-bold shadow-sm hover:opacity-95 flex items-center gap-1.5 transition-all"
                          >
                            <span className="material-symbols-outlined text-sm">support_agent</span>
                            <span>{askBusy ? "Escalating..." : "Escalate to Human Legal Reviewer"}</span>
                          </button>
                        ) : (
                          <div className="p-3 rounded-lg bg-surface-container text-xs text-primary font-semibold flex items-center gap-2">
                            <span className="material-symbols-outlined text-surface-tint">task_alt</span>
                            <span>Escalation submitted! Tracking ID: <code className="font-mono bg-surface-container-lowest px-1.5 py-0.5 rounded border">{escalation.tracking_id}</code></span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Paid-Source Search Consent Section */}
              <div className="bg-surface-container-lowest rounded-xl border border-surface-container p-4">
                <div className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    id="paid-consent"
                    checked={paidConsent}
                    onChange={(e) => setPaidConsent(e.target.checked)}
                    className="mt-1 w-4 h-4 text-primary focus:ring-primary rounded"
                  />
                  <div className="flex-1">
                    <label htmlFor="paid-consent" className="text-xs font-semibold text-on-surface cursor-pointer">
                      I explicitly consent to dispatching this query to paid external legal connectors (audited &amp; encrypted).
                    </label>
                    <p className="text-[11px] text-on-surface-variant mt-0.5">
                      Enables external legal databases for deeper prior-art searching beyond public statutes.
                    </p>
                    <div className="mt-3">
                      <button
                        type="button"
                        onClick={() => void searchPaidSources()}
                        disabled={!paidConsent || !question.trim()}
                        className="px-3 py-1.5 rounded-lg border border-primary text-xs font-bold text-primary hover:bg-primary-container hover:text-on-primary transition-colors disabled:opacity-50"
                      >
                        Search Paid Connector
                      </button>
                    </div>
                  </div>
                </div>

                {paidResults.length > 0 && (
                  <div className="mt-4 pt-3 border-t border-surface-container space-y-2">
                    <span className="text-xs font-bold text-on-surface">Paid Connector Results:</span>
                    {paidResults.map((res, i) => (
                      <div key={i} className="p-2.5 rounded bg-surface-container-low text-xs border border-surface-container">
                        <strong>{res.title ?? "Result"}</strong>
                        {res.summary && <p className="text-on-surface-variant mt-1">{res.summary}</p>}
                        {res.url && (
                          <a href={res.url} target="_blank" rel="noreferrer" className="text-primary hover:underline text-[11px] mt-1 inline-block">
                            View external source ↗
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TAB 2: Formulation Classifier */}
          {activeTab === "formulation-classifier" && (
            <div className="flex flex-col gap-5">
              {/* Header Ribbon */}
              <div className="bg-surface-container-lowest rounded-xl border border-surface-container p-4 shadow-sm">
                <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="px-2 py-0.5 rounded bg-secondary-fixed text-on-secondary-fixed text-[10px] font-bold uppercase">
                        Decision Engine
                      </span>
                      <span className="px-2 py-0.5 rounded bg-primary-container text-on-primary text-[10px] font-mono font-bold">
                        YAML Decision Tree
                      </span>
                    </div>
                    <h2 className="font-display font-bold text-xl text-primary">
                      Formulation Regulatory &amp; IPR Classification Wizard
                    </h2>
                    <p className="text-xs text-on-surface-variant mt-0.5">
                      Step-by-step statutory triage evaluating Section 3(p) Traditional Knowledge, Section 3(d) Bioavailability, and NBA approvals.
                    </p>
                  </div>

                  <button
                    type="button"
                    onClick={() => void moveClassification([], null)}
                    className="px-3 py-1.5 rounded-lg border border-surface-container text-xs font-semibold text-on-surface hover:bg-surface-container flex items-center gap-1.5 self-start lg:self-center cursor-pointer"
                  >
                    <span className="material-symbols-outlined text-base">restart_alt</span>
                    <span>Reset Trail</span>
                  </button>
                </div>
              </div>

              {/* Progress Steps */}
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
                <div className={`p-3 rounded-xl border text-xs flex items-center gap-2.5 ${classification.trail.length >= 0 ? "bg-primary-container text-on-primary border-transparent" : "bg-surface-container-low border-surface-container text-on-surface-variant"}`}>
                  <span className="w-6 h-6 rounded-full bg-primary-fixed text-on-primary-fixed flex items-center justify-center font-bold text-xs">1</span>
                  <div>
                    <div className="font-bold">Raw Material</div>
                    <div className="text-[10px] opacity-80">Botanical Origin</div>
                  </div>
                </div>
                <div className={`p-3 rounded-xl border text-xs flex items-center gap-2.5 ${classification.trail.length >= 1 ? "bg-primary-container text-on-primary border-transparent" : "bg-surface-container-low border-surface-container text-on-surface-variant"}`}>
                  <span className="w-6 h-6 rounded-full bg-primary-fixed text-on-primary-fixed flex items-center justify-center font-bold text-xs">2</span>
                  <div>
                    <div className="font-bold">Classical Check</div>
                    <div className="text-[10px] opacity-80">AFI / TKDL Index</div>
                  </div>
                </div>
                <div className={`p-3 rounded-xl border text-xs flex items-center gap-2.5 ${classification.trail.length >= 2 ? "bg-primary-container text-on-primary border-transparent" : "bg-surface-container-low border-surface-container text-on-surface-variant"}`}>
                  <span className="w-6 h-6 rounded-full bg-primary-fixed text-on-primary-fixed flex items-center justify-center font-bold text-xs">3</span>
                  <div>
                    <div className="font-bold">Modifications</div>
                    <div className="text-[10px] opacity-80">NDDS / Liposomal</div>
                  </div>
                </div>
                <div className={`p-3 rounded-xl border text-xs flex items-center gap-2.5 ${classification.complete ? "bg-secondary text-on-secondary border-transparent" : "bg-surface-container-low border-surface-container text-on-surface-variant"}`}>
                  <span className="w-6 h-6 rounded-full bg-secondary-fixed text-on-secondary-fixed flex items-center justify-center font-bold text-xs">4</span>
                  <div>
                    <div className="font-bold">Target Route</div>
                    <div className="text-[10px] opacity-80">Patent &amp; Regulatory</div>
                  </div>
                </div>
              </div>

              {/* Active Question Card */}
              {!classification.complete && classification.question && (
                <div className="bg-surface-container-lowest rounded-xl border border-surface-container shadow-md p-5">
                  <div className="flex items-center gap-2 text-xs font-bold text-primary mb-2 uppercase tracking-wider">
                    <span className="material-symbols-outlined text-base text-surface-tint">help</span>
                    <span>Current Question • Step {classification.trail.length + 1}</span>
                  </div>
                  <h3 className="font-display font-bold text-base sm:text-lg text-on-surface mb-4">
                    {classification.question}
                  </h3>

                  <div className="grid grid-cols-1 gap-2.5">
                    {classification.options.map((opt, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => void moveClassification(classification.trail, idx)}
                        disabled={classificationBusy}
                        className="p-3.5 rounded-xl border border-surface-container bg-surface-container-low hover:bg-primary-container hover:text-on-primary hover:border-transparent text-left transition-all flex items-center justify-between group cursor-pointer"
                      >
                        <div className="flex items-center gap-3">
                          <span className="w-6 h-6 rounded-lg bg-surface-container-lowest text-on-surface group-hover:bg-primary-fixed group-hover:text-on-primary-fixed flex items-center justify-center font-mono text-xs font-bold shadow-sm">
                            {idx + 1}
                          </span>
                          <span className="text-xs sm:text-sm font-medium">{opt}</span>
                        </div>
                        <span className="material-symbols-outlined text-base text-outline group-hover:text-on-primary transition-colors">
                          arrow_forward
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Terminal Classification Result */}
              {classification.complete && classification.result && (
                <div className="bg-surface-container-lowest rounded-xl border border-primary p-6 shadow-md space-y-4">
                  <div className="flex items-center justify-between pb-3 border-b border-surface-container">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-2xl text-surface-tint">verified</span>
                      <div>
                        <span className="text-[10px] font-bold text-surface-tint uppercase tracking-wider block">
                          Triage Complete
                        </span>
                        <h3 className="font-display font-bold text-xl text-primary">
                          {classification.result.category}
                        </h3>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={askAboutClassification}
                      className="px-3.5 py-1.5 rounded-lg bg-primary text-on-primary text-xs font-bold hover:bg-primary-container flex items-center gap-1.5 transition-colors cursor-pointer"
                    >
                      <span>Ask Sahayak about this</span>
                      <span className="material-symbols-outlined text-sm">arrow_forward</span>
                    </button>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                    <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container">
                      <span className="font-bold text-primary block mb-1">Regulatory Path</span>
                      <p className="text-on-surface-variant leading-relaxed">{classification.result.regulatory_path}</p>
                    </div>
                    <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container">
                      <span className="font-bold text-secondary block mb-1">IP Posture</span>
                      <p className="text-on-surface-variant leading-relaxed">{classification.result.ip_posture}</p>
                    </div>
                    <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container">
                      <span className="font-bold text-tertiary block mb-1">ABS / NBA Note</span>
                      <p className="text-on-surface-variant leading-relaxed">{classification.result.abs_note}</p>
                    </div>
                  </div>

                  {/* Recommended Routes */}
                  <div className="p-3 rounded-lg bg-surface-container-low text-xs border border-surface-container">
                    <span className="font-bold text-on-surface block mb-1.5">Recommended Statutory Routes:</span>
                    <div className="flex flex-wrap gap-2">
                      {classification.result.recommended_ip_routes.map((r) => (
                        <span key={r} className="px-2.5 py-1 rounded bg-surface-container-lowest border border-surface-container text-primary font-semibold text-[11px]">
                          {r}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Official Research Links */}
                  <div className="p-3 rounded-lg bg-surface-container text-xs">
                    <span className="font-bold text-on-surface block mb-1.5">Statutory Reference Portals:</span>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {classification.result.official_sources.map((s) => (
                        <a
                          key={s.url}
                          href={s.url}
                          target="_blank"
                          rel="noreferrer"
                          className="p-2 rounded bg-surface-container-lowest border border-surface-container-high hover:border-primary text-primary font-medium flex items-center justify-between"
                        >
                          <span>{s.label}</span>
                          <span className="material-symbols-outlined text-xs">open_in_new</span>
                        </a>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 3: Document Ingestion Hub */}
          {activeTab === "document-ingestion" && (
            <div className="flex flex-col gap-5">
              <div className="bg-surface-container-lowest rounded-xl border border-surface-container p-4 shadow-sm">
                <div className="flex items-center gap-2 mb-1">
                  <span className="px-2 py-0.5 rounded bg-primary-container text-on-primary text-[10px] font-mono font-bold">
                    Dual-Store Vector Sync
                  </span>
                  <span className="px-2 py-0.5 rounded bg-secondary-fixed text-on-secondary-fixed text-[10px] font-semibold">
                    PostgreSQL pgvector (1024-dim) + Pinecone (1536-dim)
                  </span>
                </div>
                <h2 className="font-display font-bold text-xl text-primary">
                  Knowledge Base Ingestion &amp; Web Scraping Hub
                </h2>
                <p className="text-xs text-on-surface-variant mt-0.5">
                  Synchronize statutes, guidelines, and AYUSH research directly into the vector knowledge base via Google Drive triggers, web scraping, or direct upload.
                </p>
              </div>

              {/* Mode Selector */}
              <div className="flex items-center gap-2 border-b border-surface-container pb-2">
                <button
                  type="button"
                  onClick={() => setIngestMode("url")}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                    ingestMode === "url"
                      ? "bg-primary text-on-primary shadow-sm"
                      : "text-on-surface-variant hover:bg-surface-container"
                  }`}
                >
                  <span className="material-symbols-outlined text-sm align-middle mr-1">language</span>
                  Web Scraper (URL)
                </button>
                <button
                  type="button"
                  onClick={() => setIngestMode("gdrive")}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                    ingestMode === "gdrive"
                      ? "bg-primary text-on-primary shadow-sm"
                      : "text-on-surface-variant hover:bg-surface-container"
                  }`}
                >
                  <span className="material-symbols-outlined text-sm align-middle mr-1">add_to_drive</span>
                  Google Drive Trigger
                </button>
                <button
                  type="button"
                  onClick={() => setIngestMode("upload")}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                    ingestMode === "upload"
                      ? "bg-primary text-on-primary shadow-sm"
                      : "text-on-surface-variant hover:bg-surface-container"
                  }`}
                >
                  <span className="material-symbols-outlined text-sm align-middle mr-1">upload_file</span>
                  Direct Upload
                </button>
              </div>

              {/* Ingestion Form */}
              <div className="bg-surface-container-lowest rounded-xl border border-surface-container p-5 shadow-sm space-y-4">
                {ingestMode === "url" && (
                  <div>
                    <label className="block text-xs font-bold text-on-surface mb-1">
                      Web Page URL to Scrape and Ingest:
                    </label>
                    <input
                      type="url"
                      value={ingestUrl}
                      onChange={(e) => setIngestUrl(e.target.value)}
                      placeholder="https://example.com/ayurveda-guidelines"
                      className="w-full p-2.5 rounded-lg bg-surface-container-low border border-surface-container text-xs text-on-surface focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                    />
                    <p className="text-[11px] text-on-surface-variant mt-1">
                      Automatically checks robots.txt, strips boilerplate HTML tags, chunks text, and embeds into pgvector &amp; Pinecone.
                    </p>
                  </div>
                )}

                {ingestMode === "gdrive" && (
                  <div>
                    <label className="block text-xs font-bold text-on-surface mb-1">
                      Google Drive File ID:
                    </label>
                    <input
                      type="text"
                      value={ingestGdriveId}
                      onChange={(e) => setIngestGdriveId(e.target.value)}
                      placeholder="1mFlOji63T0ETs5XwDsdyAkFucB9Zxgsh"
                      className="w-full p-2.5 rounded-lg bg-surface-container-low border border-surface-container text-xs text-on-surface focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                    />
                    <p className="text-[11px] text-on-surface-variant mt-1">
                      Downloads file content via service account and ingests it. Google Docs are automatically exported to plain text.
                    </p>
                  </div>
                )}

                {ingestMode === "upload" && (
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-bold text-on-surface mb-1">
                        Document Title / Filename:
                      </label>
                      <input
                        type="text"
                        value={ingestFilename}
                        onChange={(e) => setIngestFilename(e.target.value)}
                        placeholder="ayush_gazette_notification.txt"
                        className="w-full p-2.5 rounded-lg bg-surface-container-low border border-surface-container text-xs text-on-surface focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-bold text-on-surface mb-1">
                        Document Content (Text or Markdown with Frontmatter):
                      </label>
                      <textarea
                        value={ingestContent}
                        onChange={(e) => setIngestContent(e.target.value)}
                        rows={5}
                        className="w-full p-2.5 rounded-lg bg-surface-container-low border border-surface-container text-xs text-on-surface focus:outline-none focus:ring-2 focus:ring-primary font-mono resize-y"
                      />
                    </div>
                  </div>
                )}

                <div className="pt-2 flex items-center justify-between border-t border-surface-container">
                  <div className="text-[11px] text-on-surface-variant flex items-center gap-1">
                    <span className="material-symbols-outlined text-sm text-surface-tint">security</span>
                    <span>Requires Legal Reviewer Authorization (Dev Token active)</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleIngest()}
                    disabled={ingestBusy}
                    className="px-4 py-2 rounded-lg bg-primary hover:bg-primary-container text-on-primary text-xs font-bold shadow-sm flex items-center gap-1.5 transition-all cursor-pointer"
                  >
                    {ingestBusy ? (
                      <>
                        <span className="w-3 h-3 border-2 border-on-primary border-t-transparent rounded-full animate-spin" />
                        <span>Processing Ingestion...</span>
                      </>
                    ) : (
                      <>
                        <span>Ingest into Knowledge Base</span>
                        <span className="material-symbols-outlined text-sm">cloud_upload</span>
                      </>
                    )}
                  </button>
                </div>

                {/* Status Feedback */}
                {ingestError && (
                  <div className="p-3 rounded-lg bg-error-container text-on-error-container text-xs flex items-center gap-2">
                    <span className="material-symbols-outlined text-sm">error</span>
                    <span>{ingestError}</span>
                  </div>
                )}

                {ingestResult && (
                  <div className="p-4 rounded-xl bg-surface-container text-xs border border-surface-tint space-y-2">
                    <div className="flex items-center gap-2 text-surface-tint font-bold">
                      <span className="material-symbols-outlined text-base">task_alt</span>
                      <span>Ingestion Successful!</span>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                      <div className="p-2 rounded bg-surface-container-lowest">
                        <span className="text-[10px] text-on-surface-variant block">Status</span>
                        <strong className="text-primary capitalize">{ingestResult.status}</strong>
                      </div>
                      <div className="p-2 rounded bg-surface-container-lowest">
                        <span className="text-[10px] text-on-surface-variant block">Chunks Created</span>
                        <strong className="text-primary">{ingestResult.chunk_count} chunks</strong>
                      </div>
                      <div className="p-2 rounded bg-surface-container-lowest">
                        <span className="text-[10px] text-on-surface-variant block">Pinecone Dual-Sync</span>
                        <strong className={ingestResult.pinecone_synced ? "text-surface-tint" : "text-secondary"}>
                          {ingestResult.pinecone_synced ? "Synced (airag-1536)" : "Local pgvector only"}
                        </strong>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TAB 4: Statutory Knowledge Graph */}
          {activeTab === "legal-knowledge-graph" && (
            <div className="flex flex-col gap-5">
              <div className="bg-surface-container-lowest rounded-xl border border-surface-container p-4 shadow-sm">
                <h2 className="font-display font-bold text-xl text-primary">
                  AYUSH Statutory Corpus &amp; Legal Authorities
                </h2>
                <p className="text-xs text-on-surface-variant mt-0.5">
                  Core legal instruments and provisions indexed in the IP-SAKTI Sahayak relational legal knowledge graph.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="p-4 rounded-xl bg-surface-container-lowest border border-surface-container shadow-sm space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-primary-fixed text-on-primary-fixed text-[10px] font-bold">Act</span>
                    <h3 className="font-display font-bold text-sm text-primary">The Patents Act, 1970 (Section 3(p))</h3>
                  </div>
                  <p className="text-xs text-on-surface-variant leading-relaxed">
                    Excludes from patentability an invention which in effect is traditional knowledge or an aggregation or duplication of known properties of traditionally known components.
                  </p>
                  <div className="text-[11px] text-secondary font-semibold">
                    Relational Edge: APPLIES_TO_CATEGORY (Classical &amp; Generic Formulations)
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-surface-container-lowest border border-surface-container shadow-sm space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-primary-fixed text-on-primary-fixed text-[10px] font-bold">Act</span>
                    <h3 className="font-display font-bold text-sm text-primary">Biological Diversity Act, 2002 (Section 6)</h3>
                  </div>
                  <p className="text-xs text-on-surface-variant leading-relaxed">
                    Mandates prior approval of the National Biodiversity Authority (NBA Form III) before applying for any intellectual property right based on Indian biological resources.
                  </p>
                  <div className="text-[11px] text-surface-tint font-semibold">
                    Relational Edge: CROSS_REFERENCES (WIPO GRATK Treaty)
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-surface-container-lowest border border-surface-container shadow-sm space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-tertiary-fixed text-on-tertiary-fixed text-[10px] font-bold">Registry</span>
                    <h3 className="font-display font-bold text-sm text-primary">Traditional Knowledge Digital Library (TKDL)</h3>
                  </div>
                  <p className="text-xs text-on-surface-variant leading-relaxed">
                    CSIR-AYUSH repository of 250,000+ traditional Ayurvedic, Unani, and Siddha medical formulations cataloged into patent examiner classification codes.
                  </p>
                  <div className="text-[11px] text-tertiary font-semibold">
                    Access: User-operated statutory check portal
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-surface-container-lowest border border-surface-container shadow-sm space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-secondary-fixed text-on-secondary-fixed text-[10px] font-bold">Treaty</span>
                    <h3 className="font-display font-bold text-sm text-primary">WIPO GRATK Treaty (Adopted May 2024)</h3>
                  </div>
                  <p className="text-xs text-on-surface-variant leading-relaxed">
                    International diplomatic instrument establishing mandatory disclosure requirements for patent applicants whose inventions are based on genetic resources and associated traditional knowledge.
                  </p>
                  <div className="text-[11px] text-primary font-semibold">
                    Relational Edge: SUPERSEDES / HARMONIZES with Indian Patent Rules
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 5: Review & Escalations */}
          {activeTab === "human-review-escalations" && (
            <div className="flex flex-col gap-5">
              <div className="bg-surface-container-lowest rounded-xl border border-surface-container p-4 shadow-sm">
                <h2 className="font-display font-bold text-xl text-primary">
                  Human Legal Review &amp; Escalation Hub
                </h2>
                <p className="text-xs text-on-surface-variant mt-0.5">
                  Track questions escalated by researchers or flagged by model abstentions for human review by certified patent attorneys.
                </p>
              </div>

              {escalation ? (
                <div className="p-4 rounded-xl bg-surface-container-lowest border border-secondary shadow-sm space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-secondary uppercase tracking-wider">Active Escalation Case</span>
                    <span className="px-2 py-0.5 rounded-full bg-secondary-fixed text-on-secondary-fixed text-[11px] font-bold">
                      Priority: {escalation.priority}
                    </span>
                  </div>
                  <div className="text-sm font-semibold text-on-surface">Tracking ID: {escalation.tracking_id}</div>
                  <div className="text-xs text-on-surface-variant">Status: {escalation.status} (Dispatched to Legal Reviewer Queue)</div>
                </div>
              ) : (
                <div className="p-8 rounded-xl bg-surface-container-lowest border border-surface-container text-center text-xs text-on-surface-variant">
                  <span className="material-symbols-outlined text-4xl text-outline mb-2">inbox</span>
                  <p>No active escalations in this session. Questions with abstained answers can be escalated directly from the AI Assistant tab.</p>
                </div>
              )}
            </div>
          )}
        </main>
      </div>

      {/* Right Evidence & Citation Drawer */}
      {evidence.length > 0 && isEvidenceDrawerOpen && (
        <aside className="fixed right-0 top-16 bottom-0 w-80 bg-surface-container-lowest border-l border-surface-container z-40 flex flex-col shadow-[0_1px_8px_rgba(0,0,0,0.04)]">
          <div className="p-3.5 border-b border-surface-container flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-base text-primary">menu_book</span>
              <span className="text-xs font-bold text-primary">Retrieved Evidence ({evidence.length})</span>
            </div>
            <button
              type="button"
              onClick={() => setIsEvidenceDrawerOpen(false)}
              className="p-1 rounded hover:bg-surface-container text-on-surface-variant"
            >
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {evidence.map((item, idx) => (
              <div
                key={item.chunk_id}
                className={`p-3 rounded-xl border text-xs transition-all ${
                  activeCitationId === item.chunk_id
                    ? "bg-primary-fixed/20 border-primary shadow-sm"
                    : "bg-surface-container-low border-surface-container"
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-mono font-bold text-[10px] text-primary">#{idx + 1} • {item.chunk_id}</span>
                  <span className="px-1.5 py-0.5 rounded bg-primary-fixed text-on-primary-fixed font-mono text-[10px] font-bold">
                    {(item.score * 100).toFixed(0)}% Match
                  </span>
                </div>
                <div className="font-semibold text-on-surface text-xs mb-1">
                  {item.instrument} • {item.section}
                </div>
                <p className="text-[11px] text-on-surface-variant leading-relaxed line-clamp-6">
                  {item.chunk_text}
                </p>
              </div>
            ))}
          </div>
        </aside>
      )}
    </div>
  );
}
