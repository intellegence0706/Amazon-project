import type { Metadata } from "next";
import { Nav } from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sourcing Engine",
  description: "Retail arbitrage lead engine — scan retailers, match to Amazon, compute ROI.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Zilla+Slab:wght@500;600;700&family=Source+Sans+3:wght@400;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap"
        />
      </head>
      <body>
        <Nav />
        <div className="shell">{children}</div>
      </body>
    </html>
  );
}
