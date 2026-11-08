import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TRADF | Smart Money Trading Intelligence",
  description: "Market intelligence, portfolio risk planning and paper trading research terminal.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="fa" dir="rtl" suppressHydrationWarning><body>{children}</body></html>;
}
