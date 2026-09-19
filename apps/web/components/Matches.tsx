"use client";

import { useState } from "react";
import { api, type CvResponse, type MatchResponse } from "../lib/api";
import ResultsTable from "./ResultsTable";

type Props = {
  cv: CvResponse | null;
};

export default function Matches({ cv }: Props) {
  const [dense, setDense] = useState(true);
  const [limit, setLimit] = useState(10);
  const [match, setMatch] = useState<MatchResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run() {
    if (!cv) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<MatchResponse>("POST", `/cv/${cv.cv_hash}/match`, {
        params: { dense, limit },
      });
      setMatch(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Match failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="content" id="matches">
      <header className="topbar">
        <span>Matches</span>
        <span className="status-dot">Local setup</span>
      </header>

      <div className="intro matches-intro">
        <p className="eyebrow">Recommendation quality</p>
        <h1>Ranked subjects<br /><em>worth your time.</em></h1>
        <p className="lede">
          The profile query goes through the hybrid engine: keyword hits and dense (semantic) hits are
          fused with Reciprocal Rank Fusion. <b className="badge--both-txt">keyword + dense</b> results were
          surfaced by both channels — most reliable; <b className="badge--dense-txt">dense</b> means the
          subject matched semantically with no keyword overlap.
        </p>
      </div>

      {!cv ? (
        <p className="hint">Add your CV first — upload it in the “My CV” section.</p>
      ) : (
        <div className="panel">
          <p className="eyebrow">Profile query sent to the engine</p>
          <p className="query-mono mono">{match?.profile_query ?? "Run a match to build the query from your skills, projects and experience."}</p>

          <div className="match-controls">
            <label className="check">
              <input type="checkbox" checked={dense} onChange={(e) => setDense(e.target.checked)} />
              Hybrid RRF (keyword + dense)
            </label>
            <label className="field field--inline">
              <span>Limit</span>
              <input type="number" min={1} max={100} value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
            </label>
            <button type="button" onClick={() => void run()} disabled={busy}>
              {busy ? "Matching…" : "Run match"} <span aria-hidden="true">↗</span>
            </button>
          </div>
          {error && <p className="upload-message error">{error}</p>}
        </div>
      )}

      {match && (
        <div className="panel">
          <p className="eyebrow">
            {match.results.length} subject(s) ranked against this CV
          </p>
          <ResultsTable results={match.results} />
        </div>
      )}
    </section>
  );
}