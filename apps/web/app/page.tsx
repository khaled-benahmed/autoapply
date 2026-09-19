"use client";

import { useCallback, useEffect, useState } from "react";
import CvPanel from "../components/CvPanel";
import Library from "../components/Library";
import Matches from "../components/Matches";
import { api, type BookInfoRow, type CvResponse } from "../lib/api";

function Overview({ cv }: { cv: CvResponse | null }) {
  const [books, setBooks] = useState<BookInfoRow[] | null>(null);
  const [totalSubjects, setTotalSubjects] = useState(0);

  useEffect(() => {
    api<BookInfoRow[]>("GET", "/books")
      .then((rows) => {
        setBooks(rows);
        setTotalSubjects(rows.reduce((sum, row) => sum + row.subjects, 0));
      })
      .catch(() => {});
  }, [cv]);

  const signals = [
    {
      label: "Books parsed",
      value: books === null ? "…" : String(books?.length ?? 0),
      note: "Stored in the workspace",
    },
    {
      label: "Indexed subjects",
      value: books === null ? "…" : String(totalSubjects),
      note: "Keywords + dense vectors live",
    },
    {
      label: "CV profile",
      value: cv ? "Ready" : "Add your CV",
      note: cv ? `hash ${cv.cv_hash.slice(0, 10)}…` : "Unlocks matching",
    },
  ];

  return (
    <section className="content" id="overview">
      <header className="topbar">
        <span>Candidate workspace</span>
        <span className="status-dot">Indexed &amp; searchable</span>
      </header>
      <div className="intro">
        <p className="eyebrow">Recommendation engine</p>
        <h1>Find the subject<br /><em>worth your time.</em></h1>
        <p className="lede">
          Upload books, extract their subjects, then match a real CV against them. Every match shows why
          it surfaced — keyword, semantic, or both — so you can judge the quality, not trust it blindly.
        </p>
      </div>

      <div className="signal-grid">
        {signals.map((signal) => (
          <article className="signal" key={signal.label}>
            <p>{signal.label}</p>
            <strong>{signal.value}</strong>
            <span>{signal.note}</span>
          </article>
        ))}
      </div>

      <div className="launch-grid">
        <article className="launch-card primary-card">
          <div className="card-index">01</div>
          <div>
            <p className="eyebrow">Baseline</p>
            <h2>Books → index</h2>
            <p>Extract each PFE book (LLM), view its subjects, and keep the library indexed.</p>
            <a className="nav-lookup" href="#books">Go to books <span aria-hidden="true">↗</span></a>
          </div>
        </article>
        <article className="launch-card" id="cv-lookup">
          <div className="card-index">02</div>
          <div>
            <p className="eyebrow">Your context</p>
            <h2>CV → match</h2>
            <p>Upload your CV, correct what the parser misses, then review the ranked subjects.</p>
            <a className="nav-lookup" href="#matches">Go to matches <span aria-hidden="true">↗</span></a>
          </div>
        </article>
      </div>

      <section className="next-step">
        <div>
          <p className="eyebrow">How to review quality</p>
          <h2>Trust the sources, challenge ranks.</h2>
        </div>
        <p>
          A result tagged <b className="badge--both-txt">keyword + dense</b> is agreed on by both channels.
          A <b className="badge--dense-txt">dense</b> result found no keyword overlap — inspect the snippet to
          decide if it is a good semantic catch or noise worth reporting.
        </p>
      </section>
    </section>
  );
}

export default function Home() {
  const [cv, setCv] = useState<CvResponse | null>(null);
  const handleCvReady = useCallback((next: CvResponse | null) => setCv(next), []);

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">A</span><span>AutoApply</span></div>
        <nav className="nav" aria-label="Primary navigation">
          <a className="nav-link" href="#overview"><span>01</span>Overview</a>
          <a className="nav-link" href="#books"><span>02</span>PFE books</a>
          <a className="nav-link" href="#cv"><span>03</span>My CV</a>
          <a className="nav-link" href="#matches"><span>04</span>Matches</a>
        </nav>
        <div className="sidebar-note">
          <span className="eyebrow">Private by default</span>
          <p>Your documents and matches stay in your local workspace and Postgres.</p>
        </div>
      </aside>

      <div className="pages">
        <Overview cv={cv} />
        <Library />
        <CvPanel onCvReady={handleCvReady} />
        <Matches cv={cv} />
      </div>
    </main>
  );
}