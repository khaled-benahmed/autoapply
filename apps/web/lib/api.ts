export type SearchResultRow = {
  book_hash: string;
  reference: string | null;
  title: string;
  page_start: number | null;
  page_end: number | null;
  text: string;
  score: number;
  source: "keyword" | "dense" | "both";
};

export type BookInfoRow = {
  file_hash: string;
  filename: string;
  page_count: number;
  has_extraction: boolean;
  subjects: number;
};

export type IndexSubjectRow = {
  book_hash: string;
  reference: string | null;
  title: string;
  page_start: number | null;
  page_end: number | null;
  text: string;
};

export type CvProfile = {
  skills: string[];
  education: string[];
  experience: string[];
  projects: string[];
  certifications: string[];
};

export type CvResponse = {
  cv_hash: string;
  filename: string;
  profile: CvProfile;
};

export type MatchResponse = {
  cv_hash: string;
  profile_query: string;
  results: SearchResultRow[];
};

export type SearchResponse = {
  query: string;
  results: SearchResultRow[];
};

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ApiOptions = {
  json?: unknown;
  form?: FormData;
  params?: Record<string, string | boolean | number>;
};

export async function api<T>(
  method: string,
  path: string,
  opts: ApiOptions = {},
): Promise<T> {
  let url = BASE + path;
  if (opts.params) {
    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(opts.params)) {
      if (value !== undefined && value !== "") qs.set(key, String(value));
    }
    url += "?" + qs.toString();
  }
  const init: RequestInit = { method };
  if (opts.json !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.json);
  } else if (opts.form) {
    init.body = opts.form;
  }
  const res = await fetch(url, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((body as { detail?: unknown }).detail ? String((body as { detail: unknown }).detail) : res.statusText);
  return body as T;
}

export function emptyProfileText(profile: CvProfile): Record<keyof CvProfile, string> {
  return {
    skills: profile.skills.join("\n"),
    education: profile.education.join("\n"),
    experience: profile.experience.join("\n"),
    projects: profile.projects.join("\n"),
    certifications: profile.certifications.join("\n"),
  };
}

export function profileFromLines(lines: Record<keyof CvProfile, string>): CvProfile {
  const split = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
  return {
    skills: split(lines.skills),
    education: split(lines.education),
    experience: split(lines.experience),
    projects: split(lines.projects),
    certifications: split(lines.certifications),
  };
}