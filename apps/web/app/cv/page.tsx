import type { Metadata } from "next";
import CvPanel from "../../components/CvPanel";

export const metadata: Metadata = {
  title: "My CV — AutoApply",
};

export default function CvPage() {
  return <CvPanel />;
}