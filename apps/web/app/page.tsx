"use client";

import { ChangeEvent, useRef, useState } from "react";

const signals = [
  { label: "Books parsed", value: "0", note: "Start with a PFE catalog" },
  { label: "CV profile", value: "Not ready", note: "Add your CV to unlock matching" },
  { label: "Matches", value: "--", note: "Waiting for your first book" }
];

export default function Home() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadState, setUploadState] = useState<"idle" | "uploading" | "success" | "error">("idle");
  const [uploadMessage, setUploadMessage] = useState("");
  const [extractedText, setExtractedText] = useState("");

  async function uploadBook(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploadState("uploading");
    setUploadMessage(`Parsing ${file.name}`);
    setExtractedText("");
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch("http://localhost:8000/books", { method: "POST", body: formData });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Upload failed");
      setUploadState("success");
      setUploadMessage(`${result.page_count} page${result.page_count === 1 ? "" : "s"} parsed${result.used_ocr ? " with OCR" : ""}`);
      setExtractedText(result.extracted_text);
    } catch (error) {
      setUploadState("error");
      setUploadMessage(error instanceof Error ? error.message : "Upload failed");
    } finally {
      event.target.value = "";
    }
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">A</span><span>AutoApply</span></div>
        <nav className="nav" aria-label="Primary navigation">
          <a className="nav-link active" href="#overview"><span>01</span>Overview</a>
          <a className="nav-link" href="#books"><span>02</span>PFE books</a>
          <a className="nav-link" href="#cv"><span>03</span>My CV</a>
          <a className="nav-link" href="#matches"><span>04</span>Matches</a>
        </nav>
        <div className="sidebar-note">
          <span className="eyebrow">Private by default</span>
          <p>Your documents stay in your workspace until you choose a provider.</p>
        </div>
      </aside>

      <section className="content" id="overview">
        <header className="topbar"><span>Candidate workspace</span><span className="status-dot">Local setup</span></header>
        <div className="intro">
          <p className="eyebrow">Phase 1 / foundations</p>
          <h1>Find the subject<br /><em>worth your time.</em></h1>
          <p className="lede">Turn a long PFE book into a short, explainable list of opportunities matched to your actual experience.</p>
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

        <section className="launch-grid" id="books">
          <article className="launch-card primary-card">
            <div className="card-index">01</div>
            <div>
              <p className="eyebrow">Start here</p>
              <h2>Upload a PFE book</h2>
              <p>We will extract the company context and turn every subject into structured, searchable data.</p>
              <input ref={fileInputRef} className="file-input" type="file" accept="application/pdf" onChange={uploadBook} />
              <button type="button" onClick={() => fileInputRef.current?.click()} disabled={uploadState === "uploading"}>
                {uploadState === "uploading" ? "Parsing..." : "Choose PDF"} <span aria-hidden="true">↗</span>
              </button>
              {uploadMessage && <p className={`upload-message ${uploadState}`}>{uploadMessage}</p>}
              {extractedText && <pre className="extracted-preview">{extractedText.slice(0, 900)}</pre>}
            </div>
          </article>
          <article className="launch-card" id="cv">
            <div className="card-index">02</div>
            <div>
              <p className="eyebrow">Then add context</p>
              <h2>Bring your CV</h2>
              <p>Your skills and projects become the signal behind every recommendation.</p>
              <button className="quiet-button" type="button">Choose CV <span aria-hidden="true">↗</span></button>
            </div>
          </article>
        </section>

        <section className="next-step" id="matches">
          <div><p className="eyebrow">What happens next</p><h2>Parse. Search. Decide.</h2></div>
          <p>Every match will show the skills that align, the gaps to inspect, and a short rationale you can challenge.</p>
        </section>
      </section>
    </main>
  );
}
