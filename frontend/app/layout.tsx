import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "SmartMoney | Trading Intelligence", description: "Multi-timeframe Smart Money analysis and multi-user paper trading workspace" };
export default function RootLayout({children}:{children:React.ReactNode}) { return <html lang="en" suppressHydrationWarning><body>{children}</body></html>; }
