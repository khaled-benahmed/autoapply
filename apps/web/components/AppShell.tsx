"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CvProvider } from "../lib/cv-context";

const NAV = [
  { href: "/", label: "Overview", index: "01" },
  { href: "/books", label: "PFE books", index: "02" },
  { href: "/cv", label: "My CV", index: "03" },
  { href: "/matches", label: "Matches", index: "04" },
] as const;

export default function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <CvProvider>
      <main className="shell">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark">A</span>
            <span>AutoApply</span>
          </div>
          <nav className="nav" aria-label="Primary navigation">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`nav-link${isActive(item.href) ? " active" : ""}`}
              >
                <span>{item.index}</span>
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="sidebar-note">
            <span className="eyebrow">Private by default</span>
            <p>Your documents and matches stay in your local workspace and Postgres.</p>
          </div>
        </aside>
        <div className="pages">{children}</div>
      </main>
    </CvProvider>
  );
}