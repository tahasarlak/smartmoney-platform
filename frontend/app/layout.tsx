import type { Metadata } from "next";
import "./globals.css";
import "./tradf-sections.css";

export const metadata: Metadata = {
  title: "TRADF | Smart Money Trading Intelligence",
  description: "Market intelligence, portfolio performance, strategy research and paper trading workspace.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="fa" dir="rtl" suppressHydrationWarning><body>{children}</body></html>;
}
