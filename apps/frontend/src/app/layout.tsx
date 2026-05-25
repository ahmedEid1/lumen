import type { Metadata, Viewport } from "next";
import { ThemeProvider } from "next-themes";
import { Toaster } from "sonner";
import { QueryProvider } from "@/lib/query/client";
import { AuthProvider } from "@/lib/auth/store";
import { LocaleProvider } from "@/lib/i18n/provider";
import { SiteHeader } from "@/components/shared/site-header";
import { SiteFooter } from "@/components/shared/site-footer";
import { interDisplay, interBody, jetbrainsMono } from "@/lib/fonts";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: { default: "Lumen — Learn what you actually use.", template: "%s · Lumen" },
  description:
    "AI-first learning platform with a tutor grounded in the course itself, multi-modal authoring, and verifiable credentials.",
  applicationName: "Lumen",
  authors: [{ name: "Lumen" }],
  openGraph: { title: "Lumen", siteName: "Lumen", type: "website" },
  twitter: { card: "summary_large_image" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#FAFAF9" },
    { media: "(prefers-color-scheme: dark)", color: "#0A0B0D" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${interBody.variable} ${interDisplay.variable} ${jetbrainsMono.variable}`}
    >
      <body className="min-h-screen bg-background text-foreground antialiased">
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
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
                {/* theme="dark" pinned explicitly: the app's color-scheme
                    is dark by default and Sonner's `richColors` doesn't
                    pick that up reliably in Playwright (headless Chromium
                    inherits prefers-color-scheme=light), so success toasts
                    were rendering with light-mode greens (#008a2e on
                    #ecfdf3 = 4.25:1) and failing axe-core's WCAG 1.4.3
                    gate on every authenticated route. Pinning theme="dark"
                    forces the dark-mode toast palette which has the
                    contrast headroom AA needs. */}
                <Toaster richColors theme="dark" position="top-center" />
              </AuthProvider>
            </QueryProvider>
          </LocaleProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
