"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { formatRelative } from "@/lib/utils";

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
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");

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
      toast.success("Thread posted");
      qc.invalidateQueries({ queryKey: ["course", courseQ.data?.id, "discussions"] });
    },
    onError: (e: Error) => toast.error(e?.message ?? "Could not post"),
  });

  if (courseQ.isLoading) {
    return <div className="container mx-auto px-4 py-10">Loading…</div>;
  }
  if (!courseQ.data) {
    return (
      <div className="container mx-auto px-4 py-10 text-muted-foreground">
        Course not found.
      </div>
    );
  }
  const course = courseQ.data;

  return (
    <div className="container mx-auto max-w-3xl space-y-6 px-4 py-10">
      <header className="space-y-1">
        <Link
          href={`/courses/${course.slug}`}
          className="text-sm text-muted-foreground hover:underline"
        >
          ← {course.title}
        </Link>
        <h1 className="text-2xl font-bold tracking-tight">Discussions</h1>
      </header>

      {user && (
        <Card>
          <CardHeader>
            <CardTitle>Start a thread</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (title.trim().length < 3) return;
                create.mutate();
              }}
            >
              <Input
                placeholder="Title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                minLength={3}
                maxLength={240}
                required
              />
              <Textarea
                placeholder="Optional context — what have you tried?"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={3}
                maxLength={10000}
              />
              <Button type="submit" disabled={create.isPending || title.trim().length < 3}>
                {create.isPending ? "Posting…" : "Post thread"}
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{threadsQ.data?.total ?? 0} threads</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {threadsQ.isLoading ? (
            <p className="px-4 py-6 text-sm text-muted-foreground">Loading…</p>
          ) : !threadsQ.data?.items.length ? (
            <p className="px-4 py-6 text-sm text-muted-foreground">
              No threads yet. Start the conversation above.
            </p>
          ) : (
            <ul className="divide-y">
              {threadsQ.data.items.map((t) => (
                <li key={t.id}>
                  <Link
                    href={`/courses/${course.slug}/discussions/${t.id}`}
                    className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-muted/40"
                  >
                    <div className="flex items-start gap-3">
                      <Avatar className="h-8 w-8">
                        <AvatarImage
                          src={t.author?.avatar_url ?? undefined}
                          alt={t.author?.full_name ?? ""}
                        />
                        <AvatarFallback>
                          {(t.author?.full_name ?? "?").slice(0, 1).toUpperCase()}
                        </AvatarFallback>
                      </Avatar>
                      <div>
                        <p className="font-medium">{t.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {t.author?.full_name ?? "Deleted user"} ·{" "}
                          {formatRelative(t.last_activity_at)}
                        </p>
                      </div>
                    </div>
                    <span className="rounded-full bg-muted px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
                      {t.reply_count}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
