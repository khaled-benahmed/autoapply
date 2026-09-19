import type { Metadata } from "next";
import Library from "../../components/Library";

export const metadata: Metadata = {
  title: "PFE books — AutoApply",
};

export default function BooksPage() {
  return <Library />;
}