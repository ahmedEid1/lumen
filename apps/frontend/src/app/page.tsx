import Link from "next/link";
import { ArrowRight, BookOpen, MessagesSquare, ShieldCheck, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CourseCard } from "@/components/course/course-card";
import { Catalog } from "@/lib/api/endpoints";

export const revalidate = 60;

export default async function HomePage() {
  let featured = await Catalog.courses({ page: 1, page_size: 6, sort: "-published_at" }).catch(() => null);
  if (!featured) {
    featured = { items: [], total: 0, page: 1, page_size: 6 };
  }

  return (
    <div>
      {/* Hero */}
      <section className="relative overflow-hidden border-b">
        <div
          aria-hidden
          className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-primary/15 via-background to-background"
        />
        <div className="container mx-auto flex flex-col items-center gap-6 px-4 py-20 text-center">
          <span className="inline-flex items-center gap-2 rounded-full border bg-background/80 px-3 py-1 text-xs font-medium text-muted-foreground">
            <Sparkles className="h-3.5 w-3.5" aria-hidden /> New: real-time chat & quizzes
          </span>
          <h1 className="text-balance text-4xl font-bold tracking-tight md:text-6xl">
            Learn anything.{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Teach everything.
            </span>
          </h1>
          <p className="max-w-2xl text-balance text-lg text-muted-foreground">
            Lumen is a modern, self-hostable learning platform. Build a course in minutes, run a
            cohort live, and own your data.
          </p>
          <div className="flex flex-col gap-3 sm:flex-row">
            <Link href="/courses">
              <Button size="lg">
                Browse courses <ArrowRight className="ml-1 h-4 w-4" />
              </Button>
            </Link>
            <Link href="/register">
              <Button size="lg" variant="outline">
                Start free
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="container mx-auto px-4 py-16">
        <div className="grid gap-6 md:grid-cols-3">
          {[
            {
              icon: BookOpen,
              title: "Bring your own content",
              body: "Text, video, image, file, and auto-graded quizzes. Reorder by drag-and-drop.",
            },
            {
              icon: MessagesSquare,
              title: "Live cohort chat",
              body: "Per-course rooms with history, presence, and typing indicators. Powered by WebSockets.",
            },
            {
              icon: ShieldCheck,
              title: "Yours to host",
              body: "MIT-licensed. Docker compose up and you're running. No vendor lock-in.",
            },
          ].map(({ icon: Icon, title, body }) => (
            <Card key={title}>
              <CardHeader>
                <Icon className="h-7 w-7 text-primary" aria-hidden />
                <CardTitle>{title}</CardTitle>
                <CardDescription>{body}</CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
      </section>

      {/* Catalog teaser */}
      <section className="container mx-auto px-4 pb-20">
        <div className="mb-6 flex items-end justify-between">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Fresh from the catalog</h2>
            <p className="text-muted-foreground">A taste of what learners are picking up.</p>
          </div>
          <Link href="/courses">
            <Button variant="outline" size="sm">
              View all <ArrowRight className="ml-1 h-4 w-4" />
            </Button>
          </Link>
        </div>
        {featured.items.length === 0 ? (
          <p className="rounded-lg border bg-muted/30 p-10 text-center text-muted-foreground">
            No published courses yet. Sign in as an instructor and create the first one.
          </p>
        ) : (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {featured.items.map((c) => (
              <CourseCard key={c.id} course={c} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
