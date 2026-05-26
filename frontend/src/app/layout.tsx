import type { Metadata } from "next";
import { Geist, Geist_Mono, JetBrains_Mono, Fraunces } from "next/font/google";
import { Providers } from "./providers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// JetBrains Mono — used by the v2 design system for the .mono utility, score
// numbers, code chips, and tabular figures. Variable + tabular-nums friendly.
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

// Fraunces — variable serif used for display moments only (greeting, brand mark,
// page H1s). Variable font, so we don't specify weights — axes give us full
// control over weight + optical size + softness.
const fraunces = Fraunces({
  variable: "--font-display",
  subsets: ["latin"],
  style: ["normal", "italic"],
  axes: ["opsz", "SOFT"],
});

export const metadata: Metadata = {
  title: "Job Hunt Pipeline",
  description: "Automated job discovery, scoring, and application tailoring",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      data-theme="dark"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${jetbrainsMono.variable} ${fraunces.variable} antialiased`}
    >
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('theme');if(t==='light'||t==='dark'){document.documentElement.setAttribute('data-theme',t)}}catch(e){}`,
          }}
        />
      </head>
      <body className="flex flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
