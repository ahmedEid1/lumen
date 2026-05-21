"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Award, BookOpen, BookmarkCheck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { CourseCard } from "@/components/course/course-card";
import { Me } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";

export default function DashboardPage() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const enrollmentsQ = useQuery({ queryKey: qk.enrollments, queryFn: () => Me.enrollments() });
  const bookmarksQ = useQuery({ queryKey: qk.bookmarks, queryFn: () => Me.bookmarks() });

  useEffect(() => {
    if (ready && !user) router.replace("/login?next=/dashboard");
  }, [ready, user, router]);

  if (!ready || !user) return null;

  const enrollments = enrollmentsQ.data ?? [];
  const inProgress = enrollments.filter((e) => !e.completed_at);
  const done = enrollments.filter((e) => e.completed_at);

  return (
    <div className="container mx-auto px-4 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Welcome, {user.full_name.split(" ")[0]}</h1>
        <p className="text-muted-foreground">Pick up where you left off.</p>
      </header>

      <div className="mb-10">
        <h2 className="mb-4 inline-flex items-center gap-2 text-xl font-semibold">
          <BookOpen className="h-5 w-5" /> In progress
        </h2>
        {inProgress.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center">
              <p className="text-muted-foreground">
                You aren&apos;t enrolled in any course yet.{" "}
                <Link href="/courses" className="text-primary underline-offset-2 hover:underline">
                  Browse the catalog
                </Link>
                .
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {inProgress.map((e) => (
              <Card key={e.id}>
                <CardHeader>
                  <CardTitle>
                    <Link href={`/courses/${e.course.slug}`} className="hover:underline">
                      {e.course.title}
                    </Link>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <Progress value={e.progress_pct} />
                  <p className="text-sm text-muted-foreground">{e.progress_pct.toFixed(0)}% complete</p>
                  <Link
                    href={`/learn/${e.course.slug}`}
                    className="text-sm text-primary hover:underline"
                  >
                    Continue →
                  </Link>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {bookmarksQ.data && bookmarksQ.data.length > 0 && (
        <div className="mb-10">
          <h2 className="mb-4 inline-flex items-center gap-2 text-xl font-semibold">
            <BookmarkCheck className="h-5 w-5" /> Bookmarks
          </h2>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {bookmarksQ.data.map((c) => (
              <CourseCard key={c.id} course={c} />
            ))}
          </div>
        </div>
      )}

      <div>
        <h2 className="mb-4 inline-flex items-center gap-2 text-xl font-semibold">
          <Award className="h-5 w-5" /> Completed
        </h2>
        {done.length === 0 ? (
          <p className="text-muted-foreground">No completions yet.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {done.map((e) => (
              <li key={e.id} className="flex items-center justify-between rounded border p-3">
                <span>{e.course.title}</span>
                {e.certificate_id && (
                  <a
                    href={`/api/v1/certificates/${e.course.id}.pdf`}
                    className="text-primary hover:underline"
                  >
                    Certificate
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
