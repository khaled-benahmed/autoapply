"use client";

import { useEffect, useRef, useState } from "react";
import {
  api,
  type CvProfile,
  emptyProfileText,
  profileFromLines,
} from "../lib/api";
import { useCv } from "../lib/cv-context";

const FIELDS: Array<{ key: keyof CvProfile; label: string; placeholder: string }> = [
  { key: "skills", label: "Skills (one per line)", placeholder: "- Python\n- SQL" },
  { key: "education", label: "Education", placeholder: "- 2019-2022 Master Data Science" },
  { key: "experience", label: "Experience", placeholder: "- Stage data analyst" },
  { key: "projects", label: "Projects", placeholder: "- Dashboard BI" },
  { key: "certifications", label: "Certifications", placeholder: "- Deep Learning Specialization" },
];

export default function CvPanel() {
  const { cv, setCv, loading } = useCv();
  const [lines, setLines] = useState<Record<keyof CvProfile, string>>({
    skills: "",
    education: "",
    experience: "",
    projects: "",
    certifications: "",
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (cv) setLines(emptyProfileText(cv.profile));
  }, [cv]);

  function applyCv(next: typeof cv) {
    setCv(next);
  }

  async function upload(file: File) {
    setBusy(true);
    setMessage("");
    const form = new FormData();
    form.append("file", file);
    try {
      const up = await api<NonNullable<typeof cv>>("POST", "/cv", { form });
      applyCv(up);
      setMessage("Parsed — review and correct the profile below.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!cv) return;
    setBusy(true);
    setMessage("");
    try {
      const updated = await api<NonNullable<typeof cv>>("POST", `/cv/${cv.cv_hash}/profile`, {
        json: profileFromLines(lines),
      });
      applyCv(updated);
      setMessage("Profile saved ✓");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="content">
      <header className="topbar">
        <span>My CV</span>
        <span className="status-dot">Local setup</span>
      </header>

      <div className="launch-card primary-card upload-card">
        <div className="card-index">02</div>
        <h2>Bring your CV</h2>
        <p>Skills, education, experience and projects become the signal behind every recommendation.</p>
        <input ref={fileRef} className="file-input" type="file" accept=".pdf,.txt,.md,.text"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void upload(file);
            event.target.value = "";
          }} />
        <button type="button" onClick={() => fileRef.current?.click()} disabled={busy}>
          {busy ? "Parsing…" : "Choose CV"} <span aria-hidden="true">↗</span>
        </button>
        {message && <p className="upload-message">{message}</p>}
        {cv && (
          <p className="cv-note mono">hash {cv.cv_hash.slice(0, 16)}… · {cv.filename}</p>
        )}
      </div>

      {cv && (
        <div className="panel">
          <p className="eyebrow">Parsed profile</p>
          <div className="grid-4">
            {FIELDS.map((field) => (
              <label key={field.key} className="field">
                <span>{field.label}</span>
                <textarea
                  value={lines[field.key]}
                  placeholder={field.placeholder}
                  onChange={(event) =>
                    setLines((prev) => ({ ...prev, [field.key]: event.target.value }))
                  }
                />
              </label>
            ))}
          </div>
          <button type="button" onClick={() => void save()} disabled={busy || !cv}>
            {busy ? "Saving…" : "Save profile"}
          </button>
        </div>
      )}

      {!cv && !loading && (
        <div className="panel">
          <p className="hint">No CV yet — upload one above to unlock matching.</p>
        </div>
      )}
    </section>
  );
}