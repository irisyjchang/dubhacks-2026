import { Suspense } from "react";
import { isClerkConfigured } from "@/lib/auth-config";
import { AnalysisProvider } from "@/components/api/AnalysisProvider";
import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata, Viewport } from "next";
import { DM_Sans, Geist_Mono, Newsreader } from "next/font/google";
import { SessionMediaProvider } from "@/components/media/SessionMedia";
import { ExperienceShell } from "@/components/experience/ExperienceShell";
import { ServiceWorkerRegister } from "@/components/pwa/ServiceWorkerRegister";
import { APP_DESCRIPTION, APP_NAME } from "@/lib/constants";
import "./globals.css";

const dmSans = DM_Sans({
  variable: "--font-dm-sans",
  subsets: ["latin"],
});

const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  style: ["normal", "italic"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: APP_NAME,
  description: APP_DESCRIPTION,
  applicationName: APP_NAME,
  appleWebApp: {
    capable: true,
    title: APP_NAME,
    statusBarStyle: "default",
  },
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180" }],
  },
};

export const viewport: Viewport = {
  themeColor: "#e7e8ec",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const content = (
    <>
      <ServiceWorkerRegister />
      <Suspense fallback={<div className="initial-mist" />}>
        <SessionMediaProvider>
          <AnalysisProvider>
            <ExperienceShell authEnabled={isClerkConfigured()}>
              {children}
            </ExperienceShell>
          </AnalysisProvider>
        </SessionMediaProvider>
      </Suspense>
    </>
  );
  return (
    <html
      lang="en"
      className={`${dmSans.variable} ${newsreader.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col font-sans text-foreground">
        {isClerkConfigured() ? (
          <ClerkProvider
            signInUrl="/sign-in"
            signUpUrl="/sign-up"
            signInFallbackRedirectUrl="/"
            signUpFallbackRedirectUrl="/"
          >
            {content}
          </ClerkProvider>
        ) : (
          content
        )}
      </body>
    </html>
  );
}
