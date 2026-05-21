"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Courses } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";

export default function StudioPage() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const mine = useQuery({ queryKey: qk.myCourses, queryFn: () => Courses.mine(), enabled: !!user });

  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace("/login?next=/studio");
    else if (user.role === "student") router.replace("/dashboard");
  }, [ready, user, router]);

  if (!ready || !user || user.role === "student") return null;

  return (
    <div className="container mx-auto px-4 py-10">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Instructor studio</h1>
          <p className="text-muted-foreground">Manage your courses and content.</p>
        </div>
        <Link href="/studio/new">
          <Button>
            <Plus className="mr-2 h-4 w-4" /> New course
          </Button>
        </Link>
      </header>

      {mine.isLoading ? (
        <p>Loading…</p>
      ) : !mine.data || mine.data.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            You haven&apos;t created any courses yet.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {mine.data.map((c) => (
            <Card key={c.id}>
              <CardHeader>
                <div className="mb-1 flex items-center gap-2">
                  <Badge variant={c.status === "published" ? "default" : "muted"}>{c.status}</Badge>
                  <Badge variant="secondary">{c.subject.title}</Badge>
                </div>
                <CardTitle>
                  <Link href={`/studio/${c.id}`} className="hover:underline">
                    {c.title}
                  </Link>
                </CardTitle>
              </CardHeader>
              <CardContent className="flex items-center justify-between text-sm text-muted-foreground">
                <span>{c.modules_count} modules</span>
                <span>{c.enrollments_count} students</span>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
