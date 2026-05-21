"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search, Star, StarOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { api } from "@/lib/api/client";
import type { CourseListItem } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

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
    <div className="container mx-auto max-w-5xl px-4 py-14">
      <header className="mb-8 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex flex-col gap-3">
          <Cartouche>{t("adminCourses.cartouche")}</Cartouche>
          <h1 className="font-display text-3xl font-medium tracking-tight">
            {t("adminCourses.title")}
          </h1>
          <p className="font-body text-muted-foreground">{t("adminCourses.subtitle")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative w-72">
            <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gold/60" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("adminCourses.searchPlaceholder")}
              className="border-gold/25 bg-background/60 ps-9 focus-visible:border-gold/60"
            />
          </div>
          <label className="inline-flex items-center gap-2 font-body text-sm">
            <input
              type="checkbox"
              checked={onlyFeatured}
              onChange={(e) => setOnlyFeatured(e.target.checked)}
              className="h-4 w-4 rounded border-gold/40 accent-[hsl(var(--gold-leaf))]"
            />
            {t("adminCourses.featuredOnly")}
          </label>
        </div>
      </header>

      <Card className="scroll-paper border-gold/20">
        <CardHeader>
          <CardTitle className="font-display text-xl">{t("adminCourses.allCard")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-gold/15 bg-muted/30 text-[0.65rem] uppercase tracking-[0.28em] text-gold/70">
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
                    className="border-t border-border align-middle transition-colors hover:bg-muted/20"
                  >
                    <td className="px-4 py-3">
                      <Link
                        href={`/courses/${c.slug}`}
                        className="font-display text-base font-medium transition-colors hover:text-gold"
                        target="_blank"
                      >
                        {c.title}
                      </Link>
                      <div className="text-xs text-muted-foreground">{c.subject.title}</div>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{c.owner.full_name}</td>
                    <td className="px-4 py-3">
                      <Badge
                        className={
                          c.status === "published"
                            ? "border border-gold/40 bg-gold/10 uppercase tracking-wider text-gold"
                            : c.status === "archived"
                              ? "bg-muted uppercase tracking-wider text-muted-foreground"
                              : "bg-secondary uppercase tracking-wider text-secondary-foreground"
                        }
                      >
                        {t(`studio.filter.${c.status}` as MessageKey)}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      {c.is_featured ? (
                        <Badge className="border border-gold/40 bg-gold/10 text-gold">
                          {t("catalog.featuredBadge")}
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => toggle.mutate({ id: c.id, next: !c.is_featured })}
                        disabled={toggle.isPending}
                        className="text-muted-foreground hover:text-gold"
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
                      <div className="flex flex-col items-center gap-3 text-center">
                        <Glyph
                          name="feather"
                          size={40}
                          mode="tint"
                          className="text-gold/40"
                        />
                        <p className="font-body italic text-muted-foreground">
                          {t("adminCourses.empty")}
                        </p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
