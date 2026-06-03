"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Courses } from "@/lib/api/endpoints";
import type { CourseListItem } from "@/lib/api/types";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

/**
 * Admin moderation queue (S2.12).
 *
 * S2 ships the QUEUE VIEW — the read surface listing courses awaiting review.
 * The approve / reject / delist / relist / remove ACTIONS are S6's; they layer
 * onto this page. Content is rendered as inert text (FR-MOD-13): no markdown /
 * HTML evaluation of user-supplied titles/overviews here.
 */
export default function AdminModerationPage() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const t = useT();

  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace("/login?next=/admin/moderation");
    else if (user.role !== "admin") router.replace("/dashboard");
  }, [ready, user, router]);

  const queueQ = useQuery({
    queryKey: qk.moderationQueue,
    queryFn: () => Courses.moderationQueue(),
    enabled: !!user && user.role === "admin",
  });

  if (!ready || !user || user.role !== "admin") return null;

  const rows: CourseListItem[] = queueQ.data ?? [];

  return (
    <div className="container mx-auto px-6 py-14">
      <header className="mb-10 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("adminModeration.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("adminModeration.title")}
        </h1>
        <p className="font-body text-sm text-muted-foreground">
          {t("adminModeration.subtitle")}
        </p>
      </header>

      {queueQ.isLoading ? (
        <p className="font-body text-sm text-muted-foreground">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="font-body text-sm text-muted-foreground" data-testid="moderation-empty">
          {t("adminModeration.empty")}
        </p>
      ) : (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-start font-mono text-xs uppercase tracking-wider text-muted-foreground">
              <th className="py-2 text-start">{t("adminModeration.col.course")}</th>
              <th className="py-2 text-start">{t("adminModeration.col.owner")}</th>
              <th className="py-2 text-start">{t("adminModeration.col.submitted")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-b border-border" data-testid="moderation-row">
                <td className="py-3">
                  {/* Inert text — never render user content as markup (FR-MOD-13). */}
                  <Link href={`/courses/${c.slug}`} className="font-body hover:underline">
                    {c.title}
                  </Link>
                  <div className="mt-1 flex gap-2">
                    <Badge variant="outline">{c.visibility}</Badge>
                    {c.moderation_state ? (
                      <Badge variant="outline">{c.moderation_state}</Badge>
                    ) : null}
                  </div>
                </td>
                <td className="py-3 font-body text-muted-foreground">{c.owner.full_name}</td>
                <td className="py-3 font-mono text-xs tabular-nums text-muted-foreground">
                  {new Date(c.created_at).toLocaleDateString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
