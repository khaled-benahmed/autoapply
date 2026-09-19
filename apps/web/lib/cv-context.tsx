"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, type CvResponse } from "./api";

const STORAGE_KEY = "autoapply_cv_last_hash";

type CvContextValue = {
  cv: CvResponse | null;
  setCv: (cv: CvResponse | null) => void;
  loading: boolean;
};

const CvContext = createContext<CvContextValue>({
  cv: null,
  setCv: () => {},
  loading: false,
});

export function CvProvider({ children }: { children: ReactNode }) {
  const [cv, setCv] = useState<CvResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const hash = window.localStorage.getItem(STORAGE_KEY);
    if (!hash) {
      setLoading(false);
      return;
    }
    api<CvResponse>("GET", `/cv/${hash}`)
      .then((saved) => setCv(saved))
      .catch(() => window.localStorage.removeItem(STORAGE_KEY))
      .finally(() => setLoading(false));
  }, []);

  const applyCv = useCallback((next: CvResponse | null) => {
    setCv(next);
    if (next) window.localStorage.setItem(STORAGE_KEY, next.cv_hash);
    else window.localStorage.removeItem(STORAGE_KEY);
  }, []);

  return (
    <CvContext.Provider value={{ cv, setCv: applyCv, loading }}>
      {children}
    </CvContext.Provider>
  );
}

export function useCv() {
  return useContext(CvContext);
}