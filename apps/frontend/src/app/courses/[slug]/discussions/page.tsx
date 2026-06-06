"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { formatRelative } from "@/lib/utils";
import { useT, useTN } from "@/lib/i18n/provider";

/**
 * Discussions list — Workbench repaint.
 *
 * Thread list renders as bordered rows (not cards) — a forum index
 * should read like a feed, not a gallery. The new-thread form sits on
 * the page background above the index. Reply counts in mono so they
 * line up cleanly down the right edge.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */

type Thread = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  reply_count: number;
  last_activity_at: string;
  author: { id: string; full_name: string; avatar_url: string | null } | null;
};

type ThreadsPage = { items: Thread[]; total: number; page: number; page_size: number };

type CourseDetail = {
  id: string;
  title: string;
  slug: string;
};

export default function DiscussionsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const qc = useQueryClient();
  const { user } = useAuth();
  const t = useT();
  const tn = useTN();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");

  // S7 Gate-B F2: a tombstoned author serializes through UserPublic with
  // `full_name` set to the i18n KEY "common.deletedUser" (not null), so a
  // bare `author?.full_name ?? t(...)` fallback only catches author === null
  // and would paint the raw key. Resolve BOTH cases to the shared localized
  // label (mirrors course-card.tsx). "a deleted user · 4m ago" reads fine
  // in this lowercase muted meta row — no capitalize transform needed.
  const authorName = (author: Thread["author"]) =>
    !author || author.full_name === "common.deletedUser"
      ? t("common.deletedUser")
      : author.full_name;

  const courseQ = useQuery({
    queryKey: ["course", "by-slug", slug],
    queryFn: () => api<CourseDetail>(`/api/v1/courses/${slug}`),
  });
  const threadsQ = useQuery({
    queryKey: ["course", courseQ.data?.id, "discussions"],
    queryFn: () =>
      api<ThreadsPage>(`/api/v1/courses/${courseQ.data!.id}/discussions?page_size=50`),
    enabled: !!courseQ.data,
  });

  const create = useMutation({
    mutationFn: () =>
      api<Thread>(`/api/v1/courses/${courseQ.data!.id}/discussions`, {
        method: "POST",
        body: { title, body },
      }),
    onSuccess: () => {
      setTitle("");
      setBody("");
      toast.success(t("discussions.postedToast"));
      qc.invalidateQueries({ queryKey: ["course", courseQ.data?.id, "discussions"] });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("discussions.error")),
  });

  if (courseQ.isLoading) {
    return (
      <div className="container mx-auto px-6 py-14 font-body text-sm text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  }
  if (!courseQ.data) {
    return (
      <div className="container mx-auto flex flex-col items-start gap-3 px-6 py-20">
        <p className="font-display text-xl leading-tight tracking-tight text-muted-foreground">
          {t("courseDetail.notFound")}
        </p>
      </div>
    );
  }
  const course = courseQ.data;

  return (
    <div className="container mx-auto max-w-3xl px-6 py-14">
      <Link
        href={`/courses/${course.slug}`}
        className="mb-4 inline-flex items-center font-body text-sm text-muted-foreground transition-colors duration-[160ms] hover:text-foreground"
      >
        <ArrowLeft className="me-1 h-4 w-4" /> {course.title}
      </Link>
      <header className="mb-8 flex flex-col gap-2">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("discussions.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("discussions.title")}
        </h1>
      </header>

      {user && (
        <section className="mb-10 border-t border-border pt-8">
          <h2 className="mb-4 font-display text-base leading-tight tracking-tight">
            {t("discussions.startCard")}
          </h2>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (title.trim().length < 3) return;
              create.mutate();
            }}
          >
            <Input
              placeholder={t("studioNew.field.title")}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              minLength={3}
              maxLength={240}
              required
            />
            <Textarea
              placeholder={t("discussions.bodyPlaceholder")}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={3}
              maxLength={10000}
            />
            <Button type="submit" disabled={create.isPending || title.trim().length < 3}>
              {create.isPending ? t("discussions.posting") : t("discussions.post")}
            </Button>
          </form>
        </section>
      )}

      <section className="border-t border-border pt-8">
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="font-display text-base leading-tight tracking-tight">
            {tn("discussions.threadCount", threadsQ.data?.total ?? 0)}
          </h2>
        </div>
        {threadsQ.isLoading ? (
          <p className="font-body text-sm text-muted-foreground">{t("common.loading")}</p>
        ) : !threadsQ.data?.items.length ? (
          <div className="border-t border-border py-10">
            <p className="font-body text-sm text-muted-foreground">
              {user ? t("discussions.empty") : t("discussions.emptyAnon")}
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-border border-y border-border">
            {threadsQ.data.items.map((thread) => (
              <li key={thread.id}>
                <Link
                  href={`/courses/${course.slug}/discussions/${thread.id}`}
                  className="group flex items-center justify-between gap-3 px-1 py-3 transition-colors duration-[160ms] hover:bg-muted/30"
                >
                  <div className="flex min-w-0 items-start gap-3">
                    <Avatar className="h-8 w-8 border border-border">
                      <AvatarImage
                        src={thread.author?.avatar_url ?? undefined}
                        alt={authorName(thread.author)}
                      />
                      <AvatarFallback>
                        {authorName(thread.author).slice(0, 1).toUpperCase()}
                      </AvatarFallback>
                    </Avatar>
                    <div className="min-w-0">
                      <p className="truncate font-body text-sm font-medium text-foreground transition-colors duration-[160ms] group-hover:text-muted-foreground">
                        {thread.title}
                      </p>
                      <p className="font-body text-xs text-muted-foreground">
                        {authorName(thread.author)} ·{" "}
                        {formatRelative(thread.last_activity_at)}
                      </p>
                    </div>
                  </div>
                  <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                    {thread.reply_count}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
