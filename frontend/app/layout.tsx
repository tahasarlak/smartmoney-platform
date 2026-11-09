import type { Metadata } from "next";
import "./globals.css";
import "./tradf-sections.css";
import "./beginner.css";

export const metadata: Metadata = {
  title: "TRADF | مدیریت ساده و شفاف سرمایه",
  description: "داشبورد ساده مدیریت سرمایه آزمایشی، سود و زیان، کنترل ریسک و گزارش عملکرد TRADF.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="fa" dir="rtl" suppressHydrationWarning><body>{children}</body></html>;
}
