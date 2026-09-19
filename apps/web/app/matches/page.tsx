import type { Metadata } from "next";
import Matches from "../../components/Matches";

export const metadata: Metadata = {
  title: "Matches — AutoApply",
};

export default function MatchesPage() {
  return <Matches />;
}