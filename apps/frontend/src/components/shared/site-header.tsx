"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { Moon, Sun, GraduationCap, LogOut, Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { NotificationsBell } from "@/components/shared/notifications-bell";
import { useAuth } from "@/lib/auth/store";

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Toggle theme"
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

type NavLink = { href: string; label: string };

function navLinksFor(role: "student" | "instructor" | "admin" | undefined): NavLink[] {
  const links: NavLink[] = [{ href: "/courses", label: "Catalog" }];
  if (!role) return links;
  links.push({ href: "/dashboard", label: "Dashboard" });
  if (role === "instructor" || role === "admin") links.push({ href: "/studio", label: "Studio" });
  if (role === "admin") links.push({ href: "/admin", label: "Admin" });
  return links;
}

export function SiteHeader() {
  const { user, logout, ready } = useAuth();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  // Close the mobile menu on any route change.
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  const links = navLinksFor(user?.role);

  return (
    <header className="sticky top-0 z-40 w-full border-b bg-background/70 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto flex h-16 items-center justify-between px-4">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <GraduationCap className="h-6 w-6 text-primary" aria-hidden />
          <span className="text-lg tracking-tight">Lumen</span>
        </Link>

        <nav className="hidden gap-6 text-sm md:flex" aria-label="Primary">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={`hover:text-foreground ${
                pathname?.startsWith(l.href) ? "text-foreground" : "text-muted-foreground"
              }`}
            >
              {l.label}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <ThemeToggle />
          {!ready ? (
            <div className="h-9 w-20 animate-pulse rounded-md bg-muted" aria-hidden />
          ) : user ? (
            <>
              <NotificationsBell />
              <Link href="/profile" className="hidden md:inline-flex" aria-label="Profile">
                <Avatar>
                  <AvatarImage src={user.avatar_url ?? undefined} alt={user.full_name} />
                  <AvatarFallback>{initials(user.full_name)}</AvatarFallback>
                </Avatar>
              </Link>
              <Button variant="ghost" size="sm" className="hidden md:inline-flex" onClick={() => logout()}>
                <LogOut className="mr-1 h-4 w-4" />
                Sign out
              </Button>
            </>
          ) : (
            <>
              <Link href="/login" className="hidden sm:block">
                <Button variant="ghost" size="sm">
                  Sign in
                </Button>
              </Link>
              <Link href="/register" className="hidden sm:block">
                <Button size="sm">Get started</Button>
              </Link>
            </>
          )}

          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
            aria-controls="mobile-nav"
            onClick={() => setMenuOpen((v) => !v)}
          >
            {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>
        </div>
      </div>

      {menuOpen && (
        <div id="mobile-nav" className="border-t bg-background md:hidden" role="dialog" aria-label="Mobile menu">
          <nav className="container mx-auto flex flex-col gap-1 px-4 py-3" aria-label="Mobile primary">
            {links.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                className={`rounded-md px-3 py-2 text-sm hover:bg-muted ${
                  pathname?.startsWith(l.href) ? "bg-muted font-medium" : ""
                }`}
              >
                {l.label}
              </Link>
            ))}
            <div className="my-2 border-t" />
            {ready && user ? (
              <>
                <Link href="/profile" className="flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-muted">
                  <Avatar className="h-6 w-6">
                    <AvatarImage src={user.avatar_url ?? undefined} alt={user.full_name} />
                    <AvatarFallback>{initials(user.full_name)}</AvatarFallback>
                  </Avatar>
                  <span>{user.full_name || user.email}</span>
                </Link>
                <button
                  onClick={() => logout()}
                  className="flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-muted"
                >
                  <LogOut className="h-4 w-4" /> Sign out
                </button>
              </>
            ) : (
              <>
                <Link href="/login" className="rounded-md px-3 py-2 text-sm hover:bg-muted">
                  Sign in
                </Link>
                <Link href="/register" className="rounded-md px-3 py-2 text-sm hover:bg-muted">
                  Get started
                </Link>
              </>
            )}
          </nav>
        </div>
      )}
    </header>
  );
}
