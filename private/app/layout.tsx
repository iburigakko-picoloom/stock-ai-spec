import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "株AI | 日次リサーチ",
  description: "本人専用の原予測・企業調査・評価状況。",
  robots: { index: false, follow: false },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja">
      <body className="antialiased">{children}</body>
    </html>
  );
}
