"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, Trash2 } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { formatRelative } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

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

  const threadQ = useQuery({
    queryKey: ["discussion", id],
    queryFn: () => api<ThreadDetail>(`/api/v1/discussions/${id}`),
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
      <div className="container mx-auto px-6 py-14 text-center font-body text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  if (!threadQ.data) {
    return (
      <div className="container mx-auto flex flex-col items-center gap-3 px-6 py-20 text-center">
        <p className="font-display text-2xl italic text-muted-foreground">
          {t("thread.notFound")}
        </p>
      </div>
    );
  }
  const thread = threadQ.data;
  const canEditThread = !!user && (user.id === thread.author?.id || user.role === "admin");
  const replyCountKey = thread.replies.length === 1 ? "thread.replyCountOne" : "thread.replyCount";

  return (
    <div className="container mx-auto max-w-3xl space-y-6 px-6 py-14">
      <Link
        href={`/courses/${slug}/discussions`}
        className="inline-flex items-center font-body text-sm text-muted-foreground transition-colors hover:text-primary"
      >
        <ArrowLeft className="me-1 h-4 w-4" /> {t("thread.allDiscussions")}
      </Link>

      <Card className="surface">
        <CardHeader className="space-y-3">
          <div className="flex items-start justify-between gap-3">
            <CardTitle className="font-display text-2xl">{thread.title}</CardTitle>
            <div className="flex items-center gap-1">
              {canEditThread && (
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
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 font-body text-xs text-muted-foreground">
            <Avatar className="h-5 w-5 border border-border/60">
              <AvatarImage src={thread.author?.avatar_url ?? undefined} alt="" />
              <AvatarFallback>
                {(thread.author?.full_name ?? "?").slice(0, 1)}
              </AvatarFallback>
            </Avatar>
            <span>{thread.author?.full_name ?? t("discussions.deletedUser")}</span>
            <span>· {formatRelative(thread.created_at)}</span>
          </div>
        </CardHeader>
        {thread.body && (
          <CardContent>
            <p className="whitespace-pre-wrap font-body text-sm text-foreground/90">
              {thread.body}
            </p>
          </CardContent>
        )}
      </Card>

      <h2 className="text-[0.65rem] uppercase tracking-[0.28em] text-muted-foreground">
        {t(replyCountKey, { n: thread.replies.length })}
      </h2>
      <ul className="space-y-3">
        {thread.replies.map((r) => {
          const canDelete = !!user && (user.id === r.author?.id || user.role === "admin");
          return (
            <li key={r.id}>
              <Card className="surface">
                <CardContent className="space-y-2 pt-4">
                  <div className="flex items-center justify-between font-body text-xs text-muted-foreground">
                    <span className="flex items-center gap-2">
                      <Avatar className="h-5 w-5 border border-border/60">
                        <AvatarImage src={r.author?.avatar_url ?? undefined} alt="" />
                        <AvatarFallback>
                          {(r.author?.full_name ?? "?").slice(0, 1)}
                        </AvatarFallback>
                      </Avatar>
                      <span>{r.author?.full_name ?? t("discussions.deletedUser")}</span>
                      <span>· {formatRelative(r.created_at)}</span>
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
                  <p className="whitespace-pre-wrap font-body text-sm text-foreground/90">{r.body}</p>
                </CardContent>
              </Card>
            </li>
          );
        })}
      </ul>

      {user && (
        <Card className="surface">
          <CardHeader>
            <CardTitle className="font-display text-base">{t("thread.replyCard")}</CardTitle>
          </CardHeader>
          <CardContent>
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
                rows={3}
                maxLength={10000}
                placeholder={t("thread.replyPlaceholder")}
              />
              <Button type="submit" disabled={reply.isPending || !draft.trim()}>
                {reply.isPending ? t("discussions.posting") : t("thread.post")}
              </Button>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
