"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Award, BookOpen, BookmarkCheck, ArrowRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { CourseCard } from "@/components/course/course-card";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { Me } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

export default function DashboardPage() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const t = useT();
  const enrollmentsQ = useQuery({ queryKey: qk.enrollments, queryFn: () => Me.enrollments() });
  const bookmarksQ = useQuery({ queryKey: qk.bookmarks, queryFn: () => Me.bookmarks() });

  useEffect(() => {
    if (ready && !user) router.replace("/login?next=/dashboard");
  }, [ready, user, router]);

  if (!ready || !user) return null;

  const enrollments = enrollmentsQ.data ?? [];
  const inProgress = enrollments.filter((e) => !e.completed_at);
  const done = enrollments.filter((e) => e.completed_at);
  const firstName = user.full_name.split(" ")[0] || user.full_name;

  return (
    <div className="container mx-auto px-4 py-14">
      <header className="mb-12 flex flex-col gap-3">
        <Cartouche>{t("dashboard.cartouche")}</Cartouche>
        <h1 className="font-display text-4xl font-medium leading-tight tracking-tight sm:text-5xl">
          {t("dashboard.welcome", { name: firstName })}
        </h1>
        <p className="font-body text-lg text-muted-foreground">{t("dashboard.subtitle")}</p>
      </header>

      <section className="mb-14">
        <h2 className="mb-5 inline-flex items-center gap-2.5 font-display text-2xl font-medium tracking-tight">
          <BookOpen className="h-5 w-5 text-gold/80" />
          {t("dashboard.inProgress")}
        </h2>
        {inProgress.length === 0 ? (
          <Card className="scroll-paper border-gold/20">
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <Glyph name="feather" size={48} mode="tint" className="text-gold/40" />
              <p className="font-body text-muted-foreground">
                {t("dashboard.empty.enrollments")}{" "}
                <Link
                  href="/courses"
                  className="text-gold underline-offset-4 hover:underline"
                >
                  {t("dashboard.empty.browse")}
                </Link>
                .
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {inProgress.map((e) => (
              <Card
                key={e.id}
                className="scroll-paper border-border transition-colors hover:border-gold/40"
              >
                <CardHeader>
                  <CardTitle className="font-display text-xl">
                    <Link
                      href={`/courses/${e.course.slug}`}
                      className="hover:text-gold"
                    >
                      {e.course.title}
                    </Link>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <Progress value={e.progress_pct} />
                  <p className="font-body text-sm text-muted-foreground">
                    {t("dashboard.percentComplete", { pct: e.progress_pct.toFixed(0) })}
                  </p>
                  <Link
                    href={`/learn/${e.course.slug}`}
                    className="inline-flex items-center gap-1 text-sm text-gold underline-offset-4 hover:underline"
                  >
                    {t("dashboard.continue")} <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      {bookmarksQ.data && bookmarksQ.data.length > 0 && (
        <section className="mb-14">
          <h2 className="mb-5 inline-flex items-center gap-2.5 font-display text-2xl font-medium tracking-tight">
            <BookmarkCheck className="h-5 w-5 text-gold/80" />
            {t("dashboard.bookmarks")}
          </h2>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {bookmarksQ.data.map((c) => (
              <CourseCard key={c.id} course={c} />
            ))}
          </div>
        </section>
      )}

      <section>
        <h2 className="mb-5 inline-flex items-center gap-2.5 font-display text-2xl font-medium tracking-tight">
          <Award className="h-5 w-5 text-gold/80" />
          {t("dashboard.completed")}
        </h2>
        {done.length === 0 ? (
          <div className="rounded-md border border-dashed border-gold/20 bg-card/40 px-6 py-10 text-center scroll-paper">
            <Glyph name="ankh" size={40} mode="tint" className="mx-auto mb-3 text-gold/40" />
            <p className="font-body italic text-muted-foreground">
              {t("dashboard.empty.completed")}
            </p>
          </div>
        ) : (
          <ul className="space-y-2 text-sm">
            {done.map((e) => (
              <li
                key={e.id}
                className="flex items-center justify-between rounded-md border border-border bg-card/40 p-4 transition-colors hover:border-gold/40"
              >
                <span className="font-body">{e.course.title}</span>
                {e.certificate_id && (
                  <a
                    href={`/api/v1/certificates/${e.course.id}.pdf`}
                    className="inline-flex items-center gap-1 text-gold underline-offset-4 hover:underline"
                  >
                    <Glyph name="feather" size={14} mode="tint" />
                    {t("dashboard.certificate")}
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
