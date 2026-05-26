"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search, Star, StarOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import type { CourseListItem } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

/**
 * Admin courses — Workbench repaint.
 *
 * Dense table on the page background, header in mono uppercase, rows
 * separated by hairline borders. Owner names + subjects in body text,
 * statuses + featured flag as bordered badges, no nested card chrome.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */
export default function AdminCourses() {
  const qc = useQueryClient();
  const t = useT();
  const [q, setQ] = useState("");
  const [onlyFeatured, setOnlyFeatured] = useState(false);

  const KEY = ["admin", "courses", { q, onlyFeatured }] as const;
  const coursesQ = useQuery({
    queryKey: KEY,
    queryFn: () => {
      const qs = new URLSearchParams();
      if (q) qs.set("q", q);
      if (onlyFeatured) qs.set("only_featured", "true");
      return api<CourseListItem[]>(`/api/v1/admin/courses${qs.toString() ? `?${qs}` : ""}`);
    },
  });

  const toggle = useMutation({
    mutationFn: ({ id, next }: { id: string; next: boolean }) =>
      api<CourseListItem>(`/api/v1/admin/courses/${id}/feature`, {
        method: "PATCH",
        body: { is_featured: next },
      }),
    onSuccess: () => {
      toast.success(t("adminCourses.successToast"));
      qc.invalidateQueries({ queryKey: ["admin", "courses"] });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("adminCourses.error")),
  });

  return (
    <div className="container mx-auto max-w-6xl px-6 py-14">
      <header className="mb-8 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex flex-col gap-3">
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("adminCourses.cartouche")}
          </p>
          <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
            {t("adminCourses.title")}
          </h1>
          <p className="font-body text-sm text-muted-foreground">{t("adminCourses.subtitle")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative w-72">
            <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("adminCourses.searchPlaceholder")}
              className="ps-9"
            />
          </div>
          <div className="inline-flex items-center gap-2 font-body text-sm">
            <Switch
              id="featured-only"
              checked={onlyFeatured}
              onCheckedChange={setOnlyFeatured}
            />
            <label htmlFor="featured-only">{t("adminCourses.featuredOnly")}</label>
          </div>
        </div>
      </header>

      <div className="surface overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/40 font-mono text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-4 py-3 text-start font-medium">
                  {t("adminCourses.col.course")}
                </th>
                <th className="px-4 py-3 text-start font-medium">
                  {t("adminCourses.col.owner")}
                </th>
                <th className="px-4 py-3 text-start font-medium">
                  {t("adminCourses.col.status")}
                </th>
                <th className="px-4 py-3 text-start font-medium">
                  {t("adminCourses.col.featured")}
                </th>
                <th className="px-4 py-3 text-end font-medium">
                  {t("adminCourses.col.action")}
                </th>
              </tr>
            </thead>
            <tbody className="font-body">
              {coursesQ.data?.map((c) => (
                <tr
                  key={c.id}
                  className="border-t border-border align-middle transition-colors duration-[160ms] hover:bg-muted/30"
                >
                  <td className="px-4 py-3">
                    <Link
                      href={`/courses/${c.slug}`}
                      className="font-body text-sm font-medium text-foreground transition-colors duration-[160ms] hover:text-muted-foreground"
                      target="_blank"
                    >
                      {c.title}
                    </Link>
                    <div className="font-body text-xs text-muted-foreground">{c.subject.title}</div>
                  </td>
                  <td className="px-4 py-3 font-body text-sm text-muted-foreground">
                    {c.owner.full_name}
                  </td>
                  <td className="px-4 py-3">
                    <Badge
                      variant={
                        c.status === "published"
                          ? "default"
                          : c.status === "archived"
                            ? "muted"
                            : "secondary"
                      }
                    >
                      {t(`studio.filter.${c.status}` as MessageKey)}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    {c.is_featured ? (
                      <Badge>{t("catalog.featuredBadge")}</Badge>
                    ) : (
                      <span className="font-mono text-xs text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-end">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => toggle.mutate({ id: c.id, next: !c.is_featured })}
                      disabled={toggle.isPending}
                    >
                      {c.is_featured ? (
                        <>
                          <StarOff className="me-1 h-4 w-4" /> {t("adminCourses.unfeature")}
                        </>
                      ) : (
                        <>
                          <Star className="me-1 h-4 w-4" /> {t("adminCourses.feature")}
                        </>
                      )}
                    </Button>
                  </td>
                </tr>
              ))}
              {!coursesQ.data?.length && (
                <tr>
                  <td colSpan={5} className="px-4 py-12">
                    <p className="text-center font-body text-sm text-muted-foreground">
                      {t("adminCourses.empty")}
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
