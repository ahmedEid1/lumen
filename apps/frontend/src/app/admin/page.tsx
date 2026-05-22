"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

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

  const tiles: { href: string; titleKey: MessageKey; bodyKey: MessageKey }[] = [
    { href: "/admin/subjects", titleKey: "admin.tile.subjects.title", bodyKey: "admin.tile.subjects.body" },
    { href: "/admin/tags", titleKey: "admin.tile.tags.title", bodyKey: "admin.tile.tags.body" },
    { href: "/admin/courses", titleKey: "admin.tile.courses.title", bodyKey: "admin.tile.courses.body" },
    { href: "/admin/users", titleKey: "admin.tile.users.title", bodyKey: "admin.tile.users.body" },
    { href: "/admin/audit", titleKey: "admin.tile.audit.title", bodyKey: "admin.tile.audit.body" },
  ];

  return (
    <div className="container mx-auto px-6 py-14">
      <header className="mb-10 flex flex-col gap-3">
        <p className="font-body text-xs font-medium uppercase tracking-[0.18em] text-primary">
          {t("admin.cartouche")}
        </p>
        <h1 className="font-display text-4xl font-medium leading-tight tracking-tight sm:text-5xl">
          {t("admin.title")}
        </h1>
        <p className="font-body text-lg text-muted-foreground">{t("admin.subtitle")}</p>
      </header>

      {stats.data && (
        <Card className="surface mb-8">
          <CardHeader>
            <CardTitle className="font-display text-2xl">{t("admin.stats.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4 lg:grid-cols-7">
              <StatTile label={t("admin.stat.users")} value={stats.data.users} />
              <StatTile label={t("admin.stat.active")} value={stats.data.active_users} />
              <StatTile label={t("admin.stat.instructors")} value={stats.data.instructors} />
              <StatTile label={t("admin.stat.courses")} value={stats.data.courses_total} />
              <StatTile label={t("admin.stat.published")} value={stats.data.courses_published} />
              <StatTile label={t("admin.stat.drafts")} value={stats.data.courses_draft} />
              <StatTile label={t("admin.stat.enrollments")} value={stats.data.enrollments} />
            </dl>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {tiles.map((tile) => (
          <Link key={tile.href} href={tile.href}>
            <Card className="surface lift-3d h-full transition-colors hover:border-primary/30">
              <CardHeader>
                <CardTitle className="font-display text-xl transition-colors hover:text-primary">
                  {t(tile.titleKey)}
                </CardTitle>
                <CardDescription className="font-body">{t(tile.bodyKey)}</CardDescription>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </div>

      <Card className="surface mt-8">
        <CardHeader>
          <CardTitle className="font-display text-2xl">{t("admin.searchIndex.title")}</CardTitle>
          <CardDescription className="font-body">{t("admin.searchIndex.body")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => reindex.mutate()} disabled={reindex.isPending}>
            <RefreshCw className={`me-2 h-4 w-4 ${reindex.isPending ? "animate-spin" : ""}`} />
            {reindex.isPending ? t("admin.searchIndex.submitting") : t("admin.searchIndex.submit")}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-border/60 bg-background/40 p-3">
      <dt className="text-[0.62rem] uppercase tracking-[0.28em] text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-display text-2xl tabular-nums">{value.toLocaleString()}</dd>
    </div>
  );
}
