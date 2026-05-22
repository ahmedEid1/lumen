"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { formatRelative } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

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
      toast.success(t("discussions.postedToast"));
      qc.invalidateQueries({ queryKey: ["course", courseQ.data?.id, "discussions"] });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("discussions.error")),
  });

  if (courseQ.isLoading) {
    return (
      <div className="container mx-auto px-6 py-14 text-center font-body text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  }
  if (!courseQ.data) {
    return (
      <div className="container mx-auto flex flex-col items-center gap-3 px-6 py-20 text-center">
        <p className="font-display text-2xl italic text-muted-foreground">
          {t("courseDetail.notFound")}
        </p>
      </div>
    );
  }
  const course = courseQ.data;

  return (
    <div className="container mx-auto max-w-3xl space-y-6 px-6 py-14">
      <Link
        href={`/courses/${course.slug}`}
        className="inline-flex items-center font-body text-sm text-muted-foreground transition-colors hover:text-primary"
      >
        <ArrowLeft className="me-1 h-4 w-4" /> {course.title}
      </Link>
      <header className="flex flex-col gap-2">
        <p className="font-body text-xs font-medium uppercase tracking-[0.18em] text-primary">
          {t("discussions.cartouche")}
        </p>
        <h1 className="font-display text-4xl font-medium leading-tight tracking-tight sm:text-5xl">
          {t("discussions.title")}
        </h1>
      </header>

      {user && (
        <Card className="surface">
          <CardHeader>
            <CardTitle className="font-display text-xl">
              {t("discussions.startCard")}
            </CardTitle>
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
          </CardContent>
        </Card>
      )}

      <Card className="surface">
        <CardHeader>
          <CardTitle className="font-display text-xl">
            {t("discussions.threadCount", { n: threadsQ.data?.total ?? 0 })}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {threadsQ.isLoading ? (
            <p className="px-4 py-6 font-body text-sm text-muted-foreground">
              {t("common.loading")}
            </p>
          ) : !threadsQ.data?.items.length ? (
            <div className="py-12 text-center">
              <p className="font-display text-xl italic text-muted-foreground">
                {t("discussions.empty")}
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-border/60">
              {threadsQ.data.items.map((thread) => (
                <li key={thread.id}>
                  <Link
                    href={`/courses/${course.slug}/discussions/${thread.id}`}
                    className="group flex items-center justify-between gap-3 px-4 py-3 transition-colors hover:bg-muted/30"
                  >
                    <div className="flex items-start gap-3">
                      <Avatar className="h-8 w-8 border border-border/60">
                        <AvatarImage
                          src={thread.author?.avatar_url ?? undefined}
                          alt={thread.author?.full_name ?? ""}
                        />
                        <AvatarFallback>
                          {(thread.author?.full_name ?? "?").slice(0, 1).toUpperCase()}
                        </AvatarFallback>
                      </Avatar>
                      <div>
                        <p className="font-display text-base font-medium transition-colors group-hover:text-primary">
                          {thread.title}
                        </p>
                        <p className="font-body text-xs text-muted-foreground">
                          {thread.author?.full_name ?? t("discussions.deletedUser")} ·{" "}
                          {formatRelative(thread.last_activity_at)}
                        </p>
                      </div>
                    </div>
                    <span className="rounded-full border border-primary/30 bg-primary/10 px-2.5 py-0.5 text-xs tabular-nums text-primary">
                      {thread.reply_count}
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
