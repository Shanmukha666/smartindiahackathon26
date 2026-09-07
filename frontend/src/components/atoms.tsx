import type { ReactNode } from "react";

export function InlineCitations({ text }: { text: string }) {
  return <>{text.split(/(\[[^\]]+\])/g).map((part, index) => /^\[[^\]]+\]$/.test(part) ? <span className="citation-chip" key={`${part}-${index}`}>{part.slice(1, -1)}</span> : <span key={`${part}-${index}`}>{part}</span>)}</>;
}

export function PanelHeading({ eyebrow, title, index }: { eyebrow: string; title: string; index: string }) {
  return <div className="panel-heading"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div><span className="panel-index">{index}</span></div>;
}

export function ResultField({ label, value }: { label: string; value: string }): ReactNode {
  return <div className="result-field"><p>{label}</p><span>{value}</span></div>;
}
