"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import { Command } from "cmdk";
import {
  BookOpen,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  Moon,
  Search,
  Settings2,
  Sparkles,
  Sun,
  User,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { Catalog } from "@/lib/api/endpoints";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";

/**
 * Workbench command palette — Cmd/Ctrl+K opens, anywhere in the
 * app. Linear/Raycast/Vercel-dashboard density mandates this; the
 * audit calls it out as the one missing surface that defines the
 * "this product is workable from the keyboard" claim.
 *
 * Built on `cmdk` (Radix-style headless library). Wrapped in our
 * Dialog primitive so it inherits the focus trap + Escape +
 * click-outside + aria-modal that Loop 10 wired up.
 *
 * Sections:
 *   - Navigate — routes adapted to the current user's role.
 *   - Search courses — type-as-you-go against the catalog endpoint.
 *   - Theme — toggle dark/light.
 *   - Account — sign out (when authenticated).
 *
 * Mounted globally from layout.tsx; one instance handles every
 * route. Keyboard listener is bound at the document level so the
 * shortcut works from any focused element.
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const router = useRouter();
  const { setTheme, resolvedTheme } = useTheme();
  const { user, logout } = useAuth();
  const t = useT();

  // Cmd/Ctrl+K toggles the palette. Bound at the document level so
  // the shortcut works regardless of focus. The custom event lets
  // a button trigger anywhere (e.g. the header Cmd+K hint) open
  // the palette without needing the keyboard shortcut.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((v) => !v);
      }
    }
    function onOpenEvent() {
      setOpen(true);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("lumen:open-command-palette", onOpenEvent);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("lumen:open-command-palette", onOpenEvent);
    };
  }, []);

  // Course search — fires only when the query is non-empty and the
  // palette is open. Debounced 200ms by the query key so each
  // keystroke doesn't slam the API.
  const debouncedQuery = useDebounced(query, 200);
  const coursesQ = useQuery({
    queryKey: ["palette", "courses", debouncedQuery],
    queryFn: () => Catalog.courses({ q: debouncedQuery, page_size: 5 }),
    enabled: open && debouncedQuery.length >= 2,
  });

  function go(path: string) {
    setOpen(false);
    setQuery("");
    router.push(path);
  }

  function doToggleTheme() {
    setTheme(resolvedTheme === "dark" ? "light" : "dark");
    setOpen(false);
  }

  function doSignOut() {
    setOpen(false);
    logout();
    router.push("/");
  }

  const navItems = useMemo(() => {
    const items: { id: string; label: string; href: string; icon: typeof Search }[] = [
      { id: "nav.home", label: t("nav.home"), href: "/", icon: Sparkles },
      { id: "nav.catalog", label: t("nav.catalog"), href: "/courses", icon: BookOpen },
    ];
    if (user) {
      items.push(
        { id: "nav.dashboard", label: t("nav.dashboard"), href: "/dashboard", icon: LayoutDashboard },
        { id: "nav.reviews", label: t("nav.reviews"), href: "/dashboard/reviews", icon: GraduationCap },
        { id: "nav.mastery", label: t("nav.mastery"), href: "/dashboard/mastery", icon: GraduationCap },
        { id: "nav.profile", label: t("nav.profile"), href: "/profile", icon: User },
      );
      if (user.role === "instructor" || user.role === "admin") {
        items.push({ id: "nav.studio", label: t("nav.studio"), href: "/studio", icon: Settings2 });
      }
      if (user.role === "admin") {
        items.push({ id: "nav.admin", label: t("nav.admin"), href: "/admin", icon: Settings2 });
      }
    }
    return items;
  }, [user, t]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        className="max-w-xl p-0 overflow-hidden"
        srLabelClose={t("common.close")}
        hideCloseButton
      >
        <DialogTitle className="sr-only">{t("palette.title")}</DialogTitle>
        <Command
          shouldFilter={false}
          className="flex flex-col"
          loop
        >
          <div className="flex items-center gap-2 border-b border-border px-3">
            <Search className="h-4 w-4 text-muted-foreground" aria-hidden />
            <Command.Input
              value={query}
              onValueChange={setQuery}
              placeholder={t("palette.placeholder")}
              className="flex h-11 w-full bg-transparent py-3 font-body text-sm text-foreground outline-none placeholder:text-muted-foreground"
            />
          </div>
          <Command.List className="max-h-80 overflow-y-auto p-2">
            <Command.Empty className="py-6 text-center font-body text-sm text-muted-foreground">
              {t("palette.empty")}
            </Command.Empty>

            {/* Navigate */}
            <Command.Group
              heading={
                <span className="px-2 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  {t("palette.section.navigate")}
                </span>
              }
            >
              {navItems
                .filter(
                  (it) =>
                    !query ||
                    it.label.toLowerCase().includes(query.toLowerCase()),
                )
                .map((it) => {
                  const Icon = it.icon;
                  return (
                    <PaletteItem
                      key={it.id}
                      onSelect={() => go(it.href)}
                      icon={<Icon className="h-3.5 w-3.5" aria-hidden />}
                    >
                      {it.label}
                    </PaletteItem>
                  );
                })}
            </Command.Group>

            {/* Course search results */}
            {debouncedQuery.length >= 2 && coursesQ.data && coursesQ.data.items.length > 0 && (
              <Command.Group
                heading={
                  <span className="px-2 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    {t("palette.section.courses")}
                  </span>
                }
              >
                {coursesQ.data.items.map((c) => (
                  <PaletteItem
                    key={c.id}
                    onSelect={() => go(`/courses/${c.slug}`)}
                    icon={<BookOpen className="h-3.5 w-3.5" aria-hidden />}
                  >
                    <span className="flex-1 truncate">{c.title}</span>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                      {c.subject.title}
                    </span>
                  </PaletteItem>
                ))}
              </Command.Group>
            )}

            {/* Theme */}
            <Command.Group
              heading={
                <span className="px-2 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  {t("palette.section.theme")}
                </span>
              }
            >
              <PaletteItem
                onSelect={doToggleTheme}
                icon={
                  resolvedTheme === "dark" ? (
                    <Sun className="h-3.5 w-3.5" aria-hidden />
                  ) : (
                    <Moon className="h-3.5 w-3.5" aria-hidden />
                  )
                }
              >
                {resolvedTheme === "dark"
                  ? t("palette.theme.light")
                  : t("palette.theme.dark")}
              </PaletteItem>
            </Command.Group>

            {/* Account */}
            {user && (
              <Command.Group
                heading={
                  <span className="px-2 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    {t("palette.section.account")}
                  </span>
                }
              >
                <PaletteItem
                  onSelect={doSignOut}
                  icon={<LogOut className="h-3.5 w-3.5" aria-hidden />}
                >
                  {t("nav.signOut")}
                </PaletteItem>
              </Command.Group>
            )}
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

function PaletteItem({
  onSelect,
  icon,
  children,
}: {
  onSelect: () => void;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Command.Item
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 font-body text-sm outline-none",
        "transition-colors duration-base",
        "data-[selected=true]:bg-muted data-[selected=true]:text-foreground",
      )}
    >
      {icon}
      {children}
    </Command.Item>
  );
}

/** Tiny debounce hook. 200ms is the sweet spot for a palette —
 *  fast enough that it feels live, slow enough that we don't burn
 *  catalog requests on every keystroke. */
function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}
