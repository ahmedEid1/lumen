"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { Moon, Sun, LogOut, Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { HeaderSearch } from "@/components/shared/header-search";
import { LocaleSwitcher } from "@/components/shared/locale-switcher";
import { NotificationsBell } from "@/components/shared/notifications-bell";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

/**
 * Lumen mark — an open square bracket with a pulsing dot inside.
 * Reads as "the container of what you're learning"; the dot is the
 * cursor that moves with you. Renders in lime; capline-height so it
 * lines up with the wordmark without ascender drift.
 */
function LumenMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d="M7 4H4v16h3" />
      <path d="M17 4h3v16h-3" />
      <circle cx="12" cy="12" r="2.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const t = useT();
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={t("header.themeToggle")}
      className="text-muted-foreground hover:text-foreground"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
    >
      <Sun className="h-5 w-5 dark:hidden" />
      <Moon className="hidden h-5 w-5 dark:block" />
    </Button>
  );
}

function initials(name: string) {
  return (
    name
      .split(" ")
      .map((s) => s[0])
      .slice(0, 2)
      .join("")
      .toUpperCase() || "U"
  );
}

type NavLink = { href: string; labelKey: MessageKey };

function navLinksFor(role: "student" | "instructor" | "admin" | undefined): NavLink[] {
  const links: NavLink[] = [{ href: "/courses", labelKey: "nav.catalog" }];
  if (!role) return links;
  links.push({ href: "/dashboard", labelKey: "nav.dashboard" });
  // Reviews is shown to everyone authenticated — instructors and admins
  // can have learner cards too if they've taken any quizzes (and the
  // empty-state copy handles the "no cards yet" case cleanly).
  links.push({ href: "/dashboard/reviews", labelKey: "nav.reviews" });
  if (role === "instructor" || role === "admin")
    links.push({ href: "/studio", labelKey: "nav.studio" });
  if (role === "admin") links.push({ href: "/admin", labelKey: "nav.admin" });
  return links;
}

export function SiteHeader() {
  const { user, logout, ready } = useAuth();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const t = useT();

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  const links = navLinksFor(user?.role);

  return (
    <header className="sticky top-0 z-40 w-full border-b border-border/60 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/65">
      <div className="container mx-auto flex h-16 items-center justify-between px-4">
        <Link href="/" className="group flex items-center gap-2">
          <LumenMark className="h-5 w-5 text-primary" />
          <span className="font-body text-base font-semibold leading-none tracking-tight text-foreground">
            Lumen
          </span>
        </Link>

        <nav
          className="hidden gap-7 text-sm md:flex"
          aria-label={t("header.primaryNav")}
        >
          {links.map((l) => {
            const active = pathname?.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                aria-current={active ? "page" : undefined}
                className={`font-body transition-colors ${
                  active
                    ? "text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {t(l.labelKey)}
              </Link>
            );
          })}
        </nav>

        <div className="flex items-center gap-2">
          <HeaderSearch className="hidden md:block" />
          <LocaleSwitcher />
          <ThemeToggle />
          {!ready ? (
            <div className="h-9 w-20 animate-pulse rounded-md bg-muted" aria-hidden />
          ) : user ? (
            <>
              <NotificationsBell />
              <Link
                href="/profile"
                className="hidden md:inline-flex"
                aria-label={t("nav.profile")}
              >
                <Avatar>
                  <AvatarImage src={user.avatar_url ?? undefined} alt={user.full_name} />
                  <AvatarFallback>{initials(user.full_name)}</AvatarFallback>
                </Avatar>
              </Link>
              <Button
                variant="ghost"
                size="sm"
                className="hidden md:inline-flex"
                onClick={() => logout()}
              >
                <LogOut className="me-1 h-4 w-4" />
                {t("nav.signOut")}
              </Button>
            </>
          ) : (
            <>
              <Link href="/login" className="hidden sm:block">
                <Button variant="ghost" size="sm">
                  {t("nav.signIn")}
                </Button>
              </Link>
              <Link href="/register" className="hidden sm:block">
                <Button size="sm">{t("nav.signUp")}</Button>
              </Link>
            </>
          )}

          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label={menuOpen ? t("header.closeMenu") : t("header.openMenu")}
            aria-expanded={menuOpen}
            aria-controls="mobile-nav"
            onClick={() => setMenuOpen((v) => !v)}
          >
            {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>
        </div>
      </div>

      {menuOpen && (
        <div
          id="mobile-nav"
          className="border-t border-border/60 bg-background md:hidden"
          role="dialog"
          aria-label={t("header.mobileMenu")}
        >
          <nav
            className="container mx-auto flex flex-col gap-1 px-4 py-3"
            aria-label={t("header.mobilePrimaryNav")}
          >
            {links.map((l) => {
              const active = pathname?.startsWith(l.href);
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-3 py-2 font-body text-sm hover:bg-muted ${
                    active ? "bg-muted font-medium" : ""
                  }`}
                >
                  {t(l.labelKey)}
                </Link>
              );
            })}
            <div className="my-2 border-t border-border/60" />
            <HeaderSearch className="px-1 py-1" />
            <div className="my-2 border-t border-border/60" />
            {ready && user ? (
              <>
                <Link
                  href="/profile"
                  className="flex items-center gap-2 rounded-md px-3 py-2 font-body text-sm hover:bg-muted"
                >
                  <Avatar className="h-6 w-6">
                    <AvatarImage src={user.avatar_url ?? undefined} alt={user.full_name} />
                    <AvatarFallback>{initials(user.full_name)}</AvatarFallback>
                  </Avatar>
                  <span>{user.full_name || user.email}</span>
                </Link>
                <button
                  onClick={() => logout()}
                  className="flex items-center gap-2 rounded-md px-3 py-2 text-start font-body text-sm hover:bg-muted"
                >
                  <LogOut className="h-4 w-4" /> {t("nav.signOut")}
                </button>
              </>
            ) : (
              <>
                <Link href="/login" className="rounded-md px-3 py-2 font-body text-sm hover:bg-muted">
                  {t("nav.signIn")}
                </Link>
                <Link
                  href="/register"
                  className="rounded-md px-3 py-2 font-body text-sm hover:bg-muted"
                >
                  {t("nav.signUp")}
                </Link>
              </>
            )}
          </nav>
        </div>
      )}
    </header>
  );
}
