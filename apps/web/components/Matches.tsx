"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type BookInfoRow, type MatchResponse } from "../lib/api";
import { useCv } from "../lib/cv-context";
import ResultsTable from "./ResultsTable";

export default function Matches() {
  const { cv, loading } = useCv();
  const [books, setBooks] = useState<BookInfoRow[] | null>(null);
  const [bookHash, setBookHash] = useState("");
  const [dense, setDense] = useState(true);
  const [limit, setLimit] = useState(10);
  const [match, setMatch] = useState<MatchResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refreshBooks = useCallback(async () => {
    try {
      const rows = await api<BookInfoRow[]>("GET", "/books");
      const indexed = rows.filter((row) => row.subjects > 0);
      setBooks(indexed);
      setBookHash((current) =>
        indexed.some((row) => row.file_hash === current) ? current : indexed[0]?.file_hash ?? "",
      );
    } catch {
      setBooks([]);
    }
  }, []);

  useEffect(() => {
    void refreshBooks();
  }, [refreshBooks]);

  const selectedBook = books?.find((book) => book.file_hash === bookHash) ?? null;

  async function run() {
    if (!cv || !bookHash) return;
    setBusy(true);
    setError("");
    setMatch(null);
    try {
      const result = await api<MatchResponse>("POST", `/cv/${cv.cv_hash}/match`, {
        params: { dense, limit, book_hash: bookHash },
      });
      setMatch(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Match failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="content">
      <header className="topbar">
        <span>Matches</span>
        <span className="status-dot">Local setup</span>
      </header>

      <div className="intro matches-intro">
        <p className="eyebrow">Recommendation quality</p>
        <h1>Ranked subjects<br /><em>worth your time.</em></h1>
        <p className="lede">
          Pick one book, run it against your CV, and let the hybrid engine rank that book&apos;s
          subjects. Keyword hits and dense (semantic) hits are fused with Reciprocal Rank Fusion.
          <b className="badge--both-txt">keyword + dense</b> results were surfaced by both channels;
          <b className="badge--dense-txt">dense</b> means the subject matched semantically with no
          keyword overlap.
        </p>
      </div>

      {!cv && !loading ? (
        <p className="hint">Add your CV first — upload it in the “My CV” section.</p>
      ) : (
        <div className="panel">
          <p className="eyebrow">Profile query sent to the engine</p>
          <p className="query-mono mono">{match?.profile_query ?? "Run a match to build the query from your skills, projects and experience."}</p>

          <div className="match-controls">
            <label className="field field--inline">
              <span>Book</span>
              <select
                value={bookHash}
                disabled={!books?.length}
                onChange={(e) => setBookHash(e.target.value)}
              >
                {!books?.length && <option value="">No indexed book</option>}
                {books?.map((book) => (
                  <option key={book.file_hash} value={book.file_hash}>
                    {book.filename} · {book.subjects} subjects
                  </option>
                ))}
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={dense} onChange={(e) => setDense(e.target.checked)} />
              Hybrid RRF (keyword + dense)
            </label>
            <label className="field field--inline">
              <span>Limit</span>
              <input type="number" min={1} max={100} value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
            </label>
            <button type="button" onClick={() => void run()} disabled={busy || !bookHash}>
              {busy ? "Matching…" : "Run match"} <span aria-hidden="true">↗</span>
            </button>
          </div>
          {error && <p className="upload-message error">{error}</p>}
          {!books?.length && !error && (
            <p className="upload-message">No indexed subjects yet — extract and index a book in “PFE books” first.</p>
          )}
        </div>
      )}

      {match && (
        <div className="panel">
          <p className="eyebrow">
            {match.results.length} subject(s) from {selectedBook?.filename ?? "this book"} ranked
            against your CV
          </p>
          {match.results.length ? (
            <ResultsTable results={match.results} />
          ) : (
            <p className="hint">No matches — nothing in this book was close to your profile.</p>
          )}
        </div>
      )}
    </section>
  );
}