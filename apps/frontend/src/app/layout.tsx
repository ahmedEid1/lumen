import type { Metadata, Viewport } from "next";
import { ThemeProvider } from "next-themes";
import { Toaster } from "sonner";
import { QueryProvider } from "@/lib/query/client";
import { AuthProvider } from "@/lib/auth/store";
import { LocaleProvider } from "@/lib/i18n/provider";
import { SiteHeader } from "@/components/shared/site-header";
import { SiteFooter } from "@/components/shared/site-footer";
import { instrumentSerif, geist, geistMono } from "@/lib/fonts";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: { default: "Skillpath — Take a path. Become it.", template: "%s · Skillpath" },
  description:
    "Modern courses for the skills you actually need. Cohort chat, hands-on projects, certificates that mean something.",
  applicationName: "Skillpath",
  authors: [{ name: "Skillpath" }],
  openGraph: { title: "Skillpath", siteName: "Skillpath", type: "website" },
  twitter: { card: "summary_large_image" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#FCFCFC" },
    { media: "(prefers-color-scheme: dark)", color: "#0A0A0A" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${instrumentSerif.variable} ${geist.variable} ${geistMono.variable}`}
    >
      <body className="min-h-screen bg-background text-foreground antialiased">
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem>
          <LocaleProvider>
            <QueryProvider>
              <AuthProvider>
                <a
                  href="#main-content"
                  className="sr-only focus:not-sr-only focus:absolute focus:start-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
                >
                  Skip to content
                </a>
                <div className="flex min-h-screen flex-col">
                  <SiteHeader />
                  <main id="main-content" className="flex-1" tabIndex={-1}>
                    {children}
                  </main>
                  <SiteFooter />
                </div>
                <Toaster richColors position="top-center" />
              </AuthProvider>
            </QueryProvider>
          </LocaleProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
