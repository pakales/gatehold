import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "GATEHOLD — Local clearance for coding agents",
    template: "%s — GATEHOLD",
  },
  description:
    "One machine. Many agents. One clearance layer. Gatehold coordinates local coding agents with workstream and host-capacity clearance.",
  applicationName: "GATEHOLD",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
  openGraph: {
    type: "website",
    title: "GATEHOLD — Every agent needs clearance",
    description:
      "One machine. Many agents. One clearance layer. Local admission control for parallel coding agents.",
    images: [
      {
        url: "/gatehold-og.png",
        width: 1200,
        height: 630,
        alt: "Gatehold clearance lanes approaching a local host core",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "GATEHOLD — Every agent needs clearance",
    description:
      "Local workstream and host-capacity clearance for parallel coding agents.",
    images: ["/gatehold-og.png"],
  },
  robots: {
    index: true,
    follow: true,
  },
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#080b0a",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable}`}>
        {children}
      </body>
    </html>
  );
}
