"use client";

import Link from "next/link";
import { useTheme } from "next-themes";
import { Moon, Sun, GraduationCap, LogOut, LayoutDashboard, BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
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

export function SiteHeader() {
  const { user, logout, ready } = useAuth();

  return (
    <header className="sticky top-0 z-40 w-full border-b bg-background/70 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto flex h-16 items-center justify-between px-4">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <GraduationCap className="h-6 w-6 text-primary" aria-hidden />
          <span className="text-lg tracking-tight">Lumen</span>
        </Link>

        <nav className="hidden gap-6 text-sm md:flex">
          <Link className="text-muted-foreground hover:text-foreground" href="/courses">
            Catalog
          </Link>
          {user && (
            <Link className="text-muted-foreground hover:text-foreground" href="/dashboard">
              Dashboard
            </Link>
          )}
          {user && (user.role === "instructor" || user.role === "admin") && (
            <Link className="text-muted-foreground hover:text-foreground" href="/studio">
              Studio
            </Link>
          )}
        </nav>

        <div className="flex items-center gap-2">
          <ThemeToggle />
          {!ready ? (
            <div className="h-9 w-20 animate-pulse rounded-md bg-muted" aria-hidden />
          ) : user ? (
            <>
              <Link href="/dashboard" className="hidden md:inline-flex">
                <Avatar>
                  <AvatarImage src={user.avatar_url ?? undefined} alt={user.full_name} />
                  <AvatarFallback>
                    {user.full_name
                      .split(" ")
                      .map((s) => s[0])
                      .slice(0, 2)
                      .join("")
                      .toUpperCase() || "U"}
                  </AvatarFallback>
                </Avatar>
              </Link>
              <Button variant="ghost" size="sm" onClick={() => logout()}>
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
              <Link href="/register">
                <Button size="sm">Get started</Button>
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
