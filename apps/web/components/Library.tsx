"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type BookInfoRow, type IndexSubjectRow } from "../lib/api";

export default function Library() {
  const [books, setBooks] = useState<BookInfoRow[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [subjects, setSubjects] = useState<{ hash: string; rows: IndexSubjectRow[] } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setBooks(await api<BookInfoRow[]>("GET", "/books"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Library load failed");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function uploadBook(file: File) {
    const form = new FormData();
    form.append("file", file);
    try {
      await api("POST", "/books", { form });
      setMessage("Book stored. Run Extract (LLM) then Index.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upload failed");
    }
  }

  async function act(hash: string, action: "extract" | "index" | "view") {
    setBusy(hash + ":" + action);
    setMessage("");
    try {
      if (action === "extract") {
        await api("POST", `/books/${hash}/extract`);
        setMessage("Extraction done.");
      } else if (action === "index") {
        const result = await api<{ indexed: number }>("POST", `/books/${hash}/index`);
        setMessage(`Indexed ${result.indexed} subject(s).`);
      } else {
        const rows = await api<IndexSubjectRow[]>("GET", `/books/${hash}/index`);
        setSubjects({ hash, rows });
      }
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `${action} failed`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="content" id="books">
      <header className="topbar">
        <span>PFE books</span>
        <span className="status-dot">Local setup</span>
      </header>

      <div className="launch-card primary-card upload-card">
        <div className="card-index">01</div>
        <h2>Upload a PFE book</h2>
        <p>Store the PDF, extract the structured subjects with the LLM step, then index them for keyword + dense search.</p>
        <input ref={fileRef} className="file-input" type="file" accept="application/pdf,.pdf"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void uploadBook(file);
            event.target.value = "";
          }} />
        <button type="button" onClick={() => fileRef.current?.click()}>
          Choose PDF <span aria-hidden="true">↗</span>
        </button>
        {message && <p className="upload-message">{message}</p>}
      </div>

      <div className="panel">
        <p className="eyebrow">Library</p>
        {!books ? (
          <p className="hint">Loading…</p>
        ) : !books.length ? (
          <p className="hint">No books yet — upload one above.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>filename</th><th>hash</th><th>pages</th><th>extracted</th><th>indexed</th><th>actions</th>
              </tr>
            </thead>
            <tbody>
              {books.map((book) => {
                const extracted = book.has_extraction ? <span className="tag tag--yes">yes</span> : <span className="tag tag--no">no</span>;
                const indexed = book.subjects > 0 ? <span className="tag tag--yes">{book.subjects} subjects</span> : <span className="tag tag--no">not indexed</span>;
                const busyKey = book.file_hash + ":";
                return (
                  <tr key={book.file_hash}>
                    <td className="filename-cell">{book.filename}</td>
                    <td className="mono">{book.file_hash.slice(0, 12)}…</td>
                    <td>{book.page_count}</td>
                    <td>{extracted}</td>
                    <td>{indexed}</td>
                    <td className="actions">
                      {!book.has_extraction && (
                        <button type="button" className="action-btn" disabled={busy?.startsWith(busyKey)}
                          onClick={() => void act(book.file_hash, "extract")}>
                          {busy === busyKey + "extract" ? "Extracting…" : "Extract (LLM)"}
                        </button>
                      )}
                      <button type="button" className="action-btn" disabled={busy?.startsWith(busyKey)}
                        onClick={() => void act(book.file_hash, "index")}>
                        {busy === busyKey + "index" ? "Indexing…" : "Index"}
                      </button>
                      <button type="button" className="action-btn" disabled={busy?.startsWith(busyKey)}
                        onClick={() => void act(book.file_hash, "view")}>
                        Subjects
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {subjects && (
        <div className="panel">
          <p className="eyebrow mono">{subjects.hash.slice(0, 16)}… — indexed subjects</p>
          {!subjects.rows.length ? (
            <p className="hint">No subjects indexed yet.</p>
          ) : (
            <table className="table">
              <thead>
                <tr><th>#</th><th>reference</th><th>title</th><th>pages</th><th>text</th></tr>
              </thead>
              <tbody>
                {subjects.rows.map((row, index) => (
                  <tr key={`${row.reference}-${index}`}>
                    <td>{index + 1}</td>
                    <td className="mono">{row.reference || "—"}</td>
                    <td>{row.title}</td>
                    <td>{row.page_start || "-"} → {row.page_end || "-"}</td>
                    <td><details><summary>snippet</summary><pre className="snippet">{row.text.slice(0, 900)}</pre></details></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}