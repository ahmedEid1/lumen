"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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
  DialogDescription,
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
  // Controlled cmdk selection. With `shouldFilter={false}` cmdk defaults
  // the highlight to the first *rendered* item; when a query filtered the
  // Navigate group down to nothing, that first item was the Theme toggle —
  // so Enter flipped the theme instead of opening the top search result
  // (QA iter16). We now drive `value` ourselves: on each new query we reset
  // the highlight to the top result (course match first, else nav match),
  // while still letting arrow keys move it within the same query.
  const [value, setValue] = useState("");
  // The element that had focus when the palette opened. The palette is
  // *controlled* (no Radix <DialogTrigger>), so Radix has nothing to
  // restore focus to on close — focus fell to <body>, stranding
  // keyboard users (WCAG 2.4.3). Capture the opener and restore it via
  // onCloseAutoFocus below.
  const openerRef = useRef<HTMLElement | null>(null);
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
        setOpen((v) => {
          // Capture the opener only on the false→true transition so a
          // toggle-close doesn't overwrite it with the dialog's own
          // focused node.
          if (!v) openerRef.current = document.activeElement as HTMLElement | null;
          return !v;
        });
      }
    }
    function onOpenEvent() {
      openerRef.current = document.activeElement as HTMLElement | null;
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

  // Nav items matching the current query (same substring filter the
  // Navigate group renders with). When there's no query, all show.
  const filteredNavItems = useMemo(
    () =>
      navItems.filter(
        (it) => !query || it.label.toLowerCase().includes(query.toLowerCase()),
      ),
    [navItems, query],
  );

  const courseResults =
    debouncedQuery.length >= 2 ? (coursesQ.data?.items ?? []) : [];

  // Stable value scheme so we can drive the highlight deterministically.
  const courseValue = (id: string) => `course:${id}`;

  // The item that should be highlighted by default for the current query.
  // With a query: top course result wins, else the first matching nav item.
  // Without a query: first nav item (cmdk's natural default — Home).
  const defaultValue = query
    ? courseResults.length > 0
      ? courseValue(courseResults[0].id)
      : (filteredNavItems[0]?.id ?? "")
    : (navItems[0]?.id ?? "");

  // Reset the highlight to the computed default whenever the query or the
  // set of course results changes. We intentionally depend on the result
  // ids (joined) rather than the array reference so a re-fetch that returns
  // the same courses doesn't yank the user's arrow-key selection. Arrow
  // keys update `value` via onValueChange and persist until the next reset.
  const resultKey = courseResults.map((c) => c.id).join(",");
  useEffect(() => {
    setValue(defaultValue);
    // defaultValue is derived from query + resultKey + filteredNavItems;
    // those are the inputs that should trigger a reset.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, resultKey]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        className="max-w-xl p-0 overflow-hidden"
        srLabelClose={t("common.close")}
        hideCloseButton
        onCloseAutoFocus={(e) => {
          // Restore focus to whatever opened the palette (the navbar
          // trigger, or wherever the Cmd+K user was). Radix can't do
          // this for a controlled dialog with no DialogTrigger.
          const el = openerRef.current;
          if (el && el.isConnected && typeof el.focus === "function") {
            e.preventDefault();
            el.focus();
          }
        }}
      >
        <DialogTitle className="sr-only">{t("palette.title")}</DialogTitle>
        <DialogDescription className="sr-only">
          {t("palette.description")}
        </DialogDescription>
        <Command
          shouldFilter={false}
          value={value}
          onValueChange={setValue}
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

            {/* Course search results — rendered first when there's a
                query so the top match (not the Theme toggle) is the
                natural Enter target. */}
            {courseResults.length > 0 && (
              <Command.Group
                heading={
                  <span className="px-2 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    {t("palette.section.courses")}
                  </span>
                }
              >
                {courseResults.map((c) => (
                  <PaletteItem
                    key={c.id}
                    value={courseValue(c.id)}
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

            {/* Navigate */}
            <Command.Group
              heading={
                <span className="px-2 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  {t("palette.section.navigate")}
                </span>
              }
            >
              {filteredNavItems.map((it) => {
                const Icon = it.icon;
                return (
                  <PaletteItem
                    key={it.id}
                    value={it.id}
                    onSelect={() => go(it.href)}
                    icon={<Icon className="h-3.5 w-3.5" aria-hidden />}
                  >
                    {it.label}
                  </PaletteItem>
                );
              })}
            </Command.Group>

            {/* Theme */}
            <Command.Group
              heading={
                <span className="px-2 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  {t("palette.section.theme")}
                </span>
              }
            >
              <PaletteItem
                value="theme-toggle"
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
                  value="sign-out"
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
  value,
  onSelect,
  icon,
  children,
}: {
  value?: string;
  onSelect: () => void;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Command.Item
      value={value}
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
