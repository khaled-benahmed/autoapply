"use client";

import { useState } from "react";
import type { SearchResultRow } from "../lib/api";

function SourceBadge({ source }: { source: SearchResultRow["source"] }) {
  const label =
    source === "both" ? "keyword + dense" : source === "dense" ? "dense match" : "keyword";
  return <span className={`badge badge--${source}`}>{label}</span>;
}

export default function ResultsTable({ results }: { results: SearchResultRow[] }) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  if (!results.length) return <p className="hint">No results.</p>;

  const toggle = (index: number) => {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  return (
    <table className="table">
      <thead>
        <tr>
          <th className="w-num">#</th>
          <th>score</th>
          <th>source</th>
          <th>subject</th>
        </tr>
      </thead>
      <tbody>
        {results.map((row, index) => (
          <tr key={`${row.book_hash}-${row.reference}-${index}`}>
            <td className="w-num">{index + 1}</td>
            <td className="mono">{row.score.toFixed(4)}</td>
            <td><SourceBadge source={row.source} /></td>
            <td className="subject-cell">
              <strong>{row.title}</strong>
              <div className="subject-meta mono">
                <span>{row.reference || "—"}</span>
                <span>
                  {row.page_start || "-"} → {row.page_end || "-"}
                </span>
                <span>{row.book_hash.slice(0, 10)}…</span>
              </div>
              <button type="button" className="snippet-toggle" onClick={() => toggle(index)}>
                {open.has(index) ? "hide snippet" : "show snippet"}
              </button>
              {open.has(index) && <pre className="snippet">{row.text.slice(0, 1200)}</pre>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}