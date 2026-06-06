"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, Pencil, Trash2 } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { formatRelative } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

/**
 * Thread detail — Workbench repaint.
 *
 * Single column. The opening post leads, replies are stacked below
 * separated by subtle border-t dividers rather than card frames. The
 * reply composer is a flat textarea + primary CTA at the bottom — the
 * single lime affordance on the page.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */

type Author = { id: string; full_name: string; avatar_url: string | null } | null;

type Reply = {
  id: string;
  body: string;
  created_at: string;
  updated_at: string;
  author: Author;
};

type ThreadDetail = {
  id: string;
  course_id: string;
  title: string;
  body: string;
  created_at: string;
  updated_at: string;
  author: Author;
  replies: Reply[];
};

export default function ThreadPage({
  params,
}: {
  params: Promise<{ slug: string; id: string }>;
}) {
  const { slug, id } = use(params);
  const qc = useQueryClient();
  const router = useRouter();
  const { user } = useAuth();
  const t = useT();
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editBody, setEditBody] = useState("");

  // S7 Gate-B F2: a tombstoned author serializes through UserPublic with
  // `full_name` set to the i18n KEY "common.deletedUser" (not null), so a
  // bare `author?.full_name ?? t(...)` fallback only catches author === null
  // and would paint the raw key. Resolve BOTH cases to the shared localized
  // label (mirrors course-card.tsx). "a deleted user · 4m ago" reads fine
  // in this lowercase muted meta row — no capitalize transform needed.
  const authorName = (author: Author) =>
    !author || author.full_name === "common.deletedUser"
      ? t("common.deletedUser")
      : author.full_name;

  const threadQ = useQuery({
    queryKey: ["discussion", id],
    queryFn: () => api<ThreadDetail>(`/api/v1/discussions/${id}`),
  });
  // The course owner can moderate threads — the backend `_can_edit` allows
  // author OR admin OR course owner. The owner id isn't on the discussion
  // payload, so read it from the course detail (shared catalog query key).
  const courseQ = useQuery({
    queryKey: ["course", "by-slug", slug],
    queryFn: () => api<{ owner?: { id: string } | null }>(`/api/v1/courses/${slug}`),
  });

  const reply = useMutation({
    mutationFn: () =>
      api<Reply>(`/api/v1/discussions/${id}/replies`, {
        method: "POST",
        body: { body: draft },
      }),
    onSuccess: () => {
      setDraft("");
      qc.invalidateQueries({ queryKey: ["discussion", id] });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("thread.postError")),
  });

  const deleteThread = useMutation({
    mutationFn: () => api<{ ok: true }>(`/api/v1/discussions/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success(t("thread.deletedToast"));
      router.replace(`/courses/${slug}/discussions`);
    },
    onError: (e: Error) => toast.error(e?.message ?? t("thread.deleteError")),
  });

  const editThread = useMutation({
    mutationFn: () =>
      api<ThreadDetail>(`/api/v1/discussions/${id}`, {
        method: "PATCH",
        body: { title: editTitle.trim(), body: editBody.trim() },
      }),
    onSuccess: () => {
      setEditing(false);
      toast.success(t("thread.editedToast"));
      qc.invalidateQueries({ queryKey: ["discussion", id] });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("thread.editError")),
  });

  const deleteReply = useMutation({
    mutationFn: (replyId: string) =>
      api<{ ok: true }>(`/api/v1/discussions/replies/${replyId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["discussion", id] });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("thread.replyDeleteError")),
  });

  if (threadQ.isLoading)
    return (
      <div className="container mx-auto px-6 py-14 font-body text-sm text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  if (!threadQ.data) {
    return (
      <div className="container mx-auto flex flex-col items-start gap-3 px-6 py-20">
        <p className="font-display text-xl leading-tight tracking-tight text-muted-foreground">
          {t("thread.notFound")}
        </p>
      </div>
    );
  }
  const thread = threadQ.data;
  const canEditThread =
    !!user &&
    (user.id === thread.author?.id ||
      user.role === "admin" ||
      user.id === courseQ.data?.owner?.id);
  const replyCountKey = thread.replies.length === 1 ? "thread.replyCountOne" : "thread.replyCount";

  return (
    <div className="container mx-auto max-w-3xl px-6 py-14">
      <Link
        href={`/courses/${slug}/discussions`}
        className="mb-4 inline-flex items-center font-body text-sm text-muted-foreground transition-colors duration-[160ms] hover:text-foreground"
      >
        <ArrowLeft className="me-1 h-4 w-4" /> {t("thread.allDiscussions")}
      </Link>

      {/* Opening post */}
      <article className="mb-10">
        {editing ? (
          <form
            className="mb-4 space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (editTitle.trim().length < 3) return;
              editThread.mutate();
            }}
          >
            <Input
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              maxLength={240}
              placeholder={t("thread.editTitlePlaceholder")}
              className="font-display text-lg"
            />
            <Textarea
              value={editBody}
              onChange={(e) => setEditBody(e.target.value)}
              rows={4}
              maxLength={10000}
              placeholder={t("thread.editBodyPlaceholder")}
            />
            <div className="flex gap-2">
              <Button
                type="submit"
                disabled={editThread.isPending || editTitle.trim().length < 3}
              >
                {t("common.save")}
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setEditing(false)}
                disabled={editThread.isPending}
              >
                {t("common.cancel")}
              </Button>
            </div>
          </form>
        ) : (
          <>
            <div className="mb-4 flex items-start justify-between gap-3">
              <h1 className="font-display text-2xl leading-tight tracking-tight sm:text-3xl">
                {thread.title}
              </h1>
              {canEditThread && (
                <div className="flex shrink-0 items-center">
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("thread.editThread")}
                    onClick={() => {
                      setEditTitle(thread.title);
                      setEditBody(thread.body);
                      setEditing(true);
                    }}
                    className="text-muted-foreground hover:text-foreground"
                  >
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("thread.deleteThread")}
                    onClick={() => deleteThread.mutate()}
                    disabled={deleteThread.isPending}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              )}
            </div>
            <div className="mb-4 flex items-center gap-2 font-body text-xs text-muted-foreground">
              <Avatar className="h-5 w-5 border border-border">
                <AvatarImage src={thread.author?.avatar_url ?? undefined} alt="" />
                <AvatarFallback>
                  {authorName(thread.author).slice(0, 1)}
                </AvatarFallback>
              </Avatar>
              <span>{authorName(thread.author)}</span>
              <span className="font-mono">· {formatRelative(thread.created_at)}</span>
            </div>
            {thread.body && (
              <p className="whitespace-pre-wrap font-body text-sm leading-relaxed text-foreground/90">
                {thread.body}
              </p>
            )}
          </>
        )}
      </article>

      {/* Replies */}
      <section className="border-t border-border pt-8">
        <h2 className="mb-5 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t(replyCountKey, { n: thread.replies.length })}
        </h2>
        <ul className="divide-y divide-border border-y border-border">
          {thread.replies.map((r) => {
            const canDelete = !!user && (user.id === r.author?.id || user.role === "admin");
            return (
              <li key={r.id} className="py-5">
                <div className="mb-2 flex items-center justify-between font-body text-xs text-muted-foreground">
                  <span className="flex items-center gap-2">
                    <Avatar className="h-5 w-5 border border-border">
                      <AvatarImage src={r.author?.avatar_url ?? undefined} alt="" />
                      <AvatarFallback>
                        {authorName(r.author).slice(0, 1)}
                      </AvatarFallback>
                    </Avatar>
                    <span>{authorName(r.author)}</span>
                    <span className="font-mono">· {formatRelative(r.created_at)}</span>
                  </span>
                  {canDelete && (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t("thread.deleteReply")}
                      onClick={() => deleteReply.mutate(r.id)}
                      disabled={deleteReply.isPending}
                      className="text-muted-foreground hover:text-destructive"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
                <p className="whitespace-pre-wrap font-body text-sm leading-relaxed text-foreground/90">
                  {r.body}
                </p>
              </li>
            );
          })}
        </ul>
      </section>

      {/* Reply composer */}
      {user && (
        <section className="mt-10 border-t border-border pt-8">
          <h2 className="mb-4 font-display text-base leading-tight tracking-tight">
            {t("thread.replyCard")}
          </h2>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!draft.trim()) return;
              reply.mutate();
            }}
          >
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={4}
              maxLength={10000}
              placeholder={t("thread.replyPlaceholder")}
            />
            <Button type="submit" disabled={reply.isPending || !draft.trim()}>
              {reply.isPending ? t("discussions.posting") : t("thread.post")}
            </Button>
          </form>
        </section>
      )}
    </div>
  );
}
