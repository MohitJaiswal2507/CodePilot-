import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "CodePilot AI — Developer Workbench",
    template: "%s — CodePilot AI",
  },
  description: "AI-powered learning, multi-stage code review, and isolated execution workbench for developers.",
  icons: {
    icon: "/icon.svg",
    apple: "/icon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`dark ${geistSans.variable} ${geistMono.variable}`}>
      <body className="antialiased bg-[#080A10] text-[#F4F4F5] min-h-screen font-sans selection:bg-[#3B82F6]/30">
        {children}
      </body>
    </html>
  );
}
