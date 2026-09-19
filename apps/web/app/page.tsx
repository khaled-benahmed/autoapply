"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type BookInfoRow } from "../lib/api";
import { useCv } from "../lib/cv-context";

export default function Home() {
  const { cv } = useCv();
  const [books, setBooks] = useState<BookInfoRow[] | null>(null);
  const [totalSubjects, setTotalSubjects] = useState(0);

  useEffect(() => {
    api<BookInfoRow[]>("GET", "/books")
      .then((rows) => {
        setBooks(rows);
        setTotalSubjects(rows.reduce((sum, row) => sum + row.subjects, 0));
      })
      .catch(() => {});
  }, []);

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
    <section className="content">
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
            <Link className="nav-lookup" href="/books">Go to books <span aria-hidden="true">↗</span></Link>
          </div>
        </article>
        <article className="launch-card" id="cv-lookup">
          <div className="card-index">02</div>
          <div>
            <p className="eyebrow">Your context</p>
            <h2>CV → match</h2>
            <p>Upload your CV, correct what the parser misses, then review the ranked subjects.</p>
            <Link className="nav-lookup" href="/matches">Go to matches <span aria-hidden="true">↗</span></Link>
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