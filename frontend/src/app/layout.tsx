import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CodePilot AI — Learning & Code Review Copilot",
  description: "AI-powered learning and automated code-review platform for developers and CS students.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased bg-[#090d16] text-slate-100 min-h-screen">
        {children}
      </body>
    </html>
  );
}

