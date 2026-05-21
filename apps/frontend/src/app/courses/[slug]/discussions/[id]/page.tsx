"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bell, BellOff, Trash2 } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { formatRelative } from "@/lib/utils";

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
  is_subscribed: boolean;
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
    onError: (e: Error) => toast.error(e?.message ?? "Could not post reply"),
  });

  const toggleSubscribe = useMutation({
    mutationFn: () =>
      api<{ ok: true }>(
        `/api/v1/discussions/${id}/subscribe`,
        { method: threadQ.data?.is_subscribed ? "DELETE" : "POST" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["discussion", id] }),
    onError: (e: Error) => toast.error(e?.message ?? "Could not update subscription"),
  });

  const deleteThread = useMutation({
    mutationFn: () => api<{ ok: true }>(`/api/v1/discussions/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Thread deleted");
      router.replace(`/courses/${slug}/discussions`);
    },
    onError: (e: Error) => toast.error(e?.message ?? "Could not delete"),
  });

  const deleteReply = useMutation({
    mutationFn: (replyId: string) =>
      api<{ ok: true }>(`/api/v1/discussions/replies/${replyId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["discussion", id] });
    },
    onError: (e: Error) => toast.error(e?.message ?? "Could not delete reply"),
  });

  if (threadQ.isLoading) return <div className="container mx-auto px-4 py-10">Loading…</div>;
  if (!threadQ.data) {
    return (
      <div className="container mx-auto px-4 py-10 text-muted-foreground">
        Thread not found.
      </div>
    );
  }
  const t = threadQ.data;
  const canEditThread = !!user && (user.id === t.author?.id || user.role === "admin");

  return (
    <div className="container mx-auto max-w-3xl space-y-6 px-4 py-10">
      <Link
        href={`/courses/${slug}/discussions`}
        className="text-sm text-muted-foreground hover:underline"
      >
        ← All discussions
      </Link>

      <Card>
        <CardHeader className="space-y-2">
          <div className="flex items-start justify-between gap-3">
            <CardTitle>{t.title}</CardTitle>
            <div className="flex items-center gap-1">
              {user && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => toggleSubscribe.mutate()}
                  disabled={toggleSubscribe.isPending}
                  title={
                    t.is_subscribed
                      ? "Stop getting notified about new replies"
                      : "Get notified when someone replies"
                  }
                >
                  {t.is_subscribed ? (
                    <>
                      <BellOff className="me-1 h-3.5 w-3.5" /> Subscribed
                    </>
                  ) : (
                    <>
                      <Bell className="me-1 h-3.5 w-3.5" /> Subscribe
                    </>
                  )}
                </Button>
              )}
              {canEditThread && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Delete thread"
                  onClick={() => deleteThread.mutate()}
                  disabled={deleteThread.isPending}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Avatar className="h-5 w-5">
              <AvatarImage src={t.author?.avatar_url ?? undefined} alt="" />
              <AvatarFallback>
                {(t.author?.full_name ?? "?").slice(0, 1)}
              </AvatarFallback>
            </Avatar>
            <span>{t.author?.full_name ?? "Deleted user"}</span>
            <span>· {formatRelative(t.created_at)}</span>
          </div>
        </CardHeader>
        {t.body && (
          <CardContent>
            <p className="whitespace-pre-wrap text-sm">{t.body}</p>
          </CardContent>
        )}
      </Card>

      <h2 className="text-sm font-medium text-muted-foreground">
        {t.replies.length} {t.replies.length === 1 ? "reply" : "replies"}
      </h2>
      <ul className="space-y-3">
        {t.replies.map((r) => {
          const canDelete = !!user && (user.id === r.author?.id || user.role === "admin");
          return (
            <li key={r.id}>
              <Card>
                <CardContent className="space-y-2 pt-4">
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span className="flex items-center gap-2">
                      <Avatar className="h-5 w-5">
                        <AvatarImage src={r.author?.avatar_url ?? undefined} alt="" />
                        <AvatarFallback>
                          {(r.author?.full_name ?? "?").slice(0, 1)}
                        </AvatarFallback>
                      </Avatar>
                      <span>{r.author?.full_name ?? "Deleted user"}</span>
                      <span>· {formatRelative(r.created_at)}</span>
                    </span>
                    {canDelete && (
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Delete reply"
                        onClick={() => deleteReply.mutate(r.id)}
                        disabled={deleteReply.isPending}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                  <p className="whitespace-pre-wrap text-sm">{r.body}</p>
                </CardContent>
              </Card>
            </li>
          );
        })}
      </ul>

      {user && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Reply</CardTitle>
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
                placeholder="Add to the conversation…"
              />
              <Button type="submit" disabled={reply.isPending || !draft.trim()}>
                {reply.isPending ? "Posting…" : "Post reply"}
              </Button>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
