"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowRight, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

/**
 * Admin home — Workbench repaint.
 *
 * Stats render as a tight surface tile grid with mono+tabular-nums for
 * every value (so admins reading numbers don't get baseline wobble).
 * The old `lift-3d` tile grid is replaced by a dense panel: each admin
 * tool is a bordered row with a title, description, and a small arrow.
 * Search reindex is a single trailing section.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */
export default function AdminHome() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const t = useT();

  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace("/login?next=/admin");
    else if (user.role !== "admin") router.replace("/dashboard");
  }, [ready, user, router]);

  const reindex = useMutation({
    mutationFn: () => api("/api/v1/admin/search/reindex", { method: "POST" }),
    onSuccess: () => toast.success(t("admin.searchIndex.toast")),
    onError: (e: Error) => toast.error(e?.message ?? t("admin.searchIndex.error")),
  });

  const stats = useQuery({
    queryKey: ["admin", "stats"],
    queryFn: () =>
      api<{
        users: number;
        active_users: number;
        instructors: number;
        courses_total: number;
        courses_published: number;
        courses_draft: number;
        enrollments: number;
      }>("/api/v1/admin/stats"),
    enabled: !!user && user.role === "admin",
  });

  if (!ready || !user || user.role !== "admin") return null;

  const tools: { href: string; titleKey: MessageKey; bodyKey: MessageKey }[] = [
    { href: "/admin/subjects", titleKey: "admin.tile.subjects.title", bodyKey: "admin.tile.subjects.body" },
    { href: "/admin/tags", titleKey: "admin.tile.tags.title", bodyKey: "admin.tile.tags.body" },
    { href: "/admin/courses", titleKey: "admin.tile.courses.title", bodyKey: "admin.tile.courses.body" },
    { href: "/admin/users", titleKey: "admin.tile.users.title", bodyKey: "admin.tile.users.body" },
    { href: "/admin/audit", titleKey: "admin.tile.audit.title", bodyKey: "admin.tile.audit.body" },
  ];

  return (
    <div className="container mx-auto px-6 py-14">
      <header className="mb-10 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("admin.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("admin.title")}
        </h1>
        <p className="font-body text-sm text-muted-foreground">{t("admin.subtitle")}</p>
      </header>

      {/* Stats panel — mono, tabular-nums. */}
      {stats.data && (
        <section className="mb-12 border-t border-border pt-8">
          <h2 className="mb-5 font-display text-lg leading-tight tracking-tight">
            {t("admin.stats.title")}
          </h2>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            <StatTile label={t("admin.stat.users")} value={stats.data.users} />
            <StatTile label={t("admin.stat.active")} value={stats.data.active_users} />
            <StatTile label={t("admin.stat.instructors")} value={stats.data.instructors} />
            <StatTile label={t("admin.stat.courses")} value={stats.data.courses_total} />
            <StatTile label={t("admin.stat.published")} value={stats.data.courses_published} />
            <StatTile label={t("admin.stat.drafts")} value={stats.data.courses_draft} />
            <StatTile label={t("admin.stat.enrollments")} value={stats.data.enrollments} />
          </dl>
        </section>
      )}

      {/* Tools — dense bordered rows, no 3D tile grid. */}
      <section className="border-t border-border pt-8">
        <h2 className="mb-5 font-display text-lg leading-tight tracking-tight">
          {t("admin.title")}
        </h2>
        <ul className="divide-y divide-border border-y border-border">
          {tools.map((tool) => (
            <li key={tool.href}>
              <Link
                href={tool.href}
                className="group flex items-center justify-between gap-4 px-1 py-4 transition-colors duration-[160ms] hover:bg-muted/30"
              >
                <div className="flex flex-col gap-1">
                  <span className="font-display text-base leading-tight tracking-tight text-foreground transition-colors duration-[160ms] group-hover:text-muted-foreground">
                    {t(tool.titleKey)}
                  </span>
                  <span className="font-body text-sm text-muted-foreground">{t(tool.bodyKey)}</span>
                </div>
                <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-colors duration-[160ms] group-hover:text-foreground" />
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-12 border-t border-border pt-8">
        <h2 className="mb-2 font-display text-lg leading-tight tracking-tight">
          {t("admin.searchIndex.title")}
        </h2>
        <p className="mb-4 max-w-2xl font-body text-sm text-muted-foreground">
          {t("admin.searchIndex.body")}
        </p>
        <Button onClick={() => reindex.mutate()} disabled={reindex.isPending}>
          <RefreshCw className={`me-2 h-4 w-4 ${reindex.isPending ? "animate-spin" : ""}`} />
          {reindex.isPending ? t("admin.searchIndex.submitting") : t("admin.searchIndex.submit")}
        </Button>
      </section>
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="surface p-4">
      <dt className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className="mt-2 font-mono text-xl tabular-nums text-foreground">
        {value.toLocaleString()}
      </dd>
    </div>
  );
}
