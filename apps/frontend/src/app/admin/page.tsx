"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";

export default function AdminHome() {
  const { user, ready } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace("/login?next=/admin");
    else if (user.role !== "admin") router.replace("/dashboard");
  }, [ready, user, router]);

  const reindex = useMutation({
    mutationFn: () => api("/api/v1/admin/search/reindex", { method: "POST" }),
    onSuccess: () => toast.success("Reindex queued"),
    onError: (e: any) => toast.error(e?.message ?? "Could not queue reindex"),
  });

  if (!ready || !user || user.role !== "admin") return null;

  const tiles = [
    { href: "/admin/subjects", title: "Subjects", body: "Manage the taxonomy of the catalog." },
    { href: "/admin/tags", title: "Tags", body: "Curate the public tag list." },
    { href: "/admin/courses", title: "Courses", body: "Oversee the catalog, set featured." },
    { href: "/admin/users", title: "Users", body: "Promote instructors, manage activity." },
    { href: "/admin/audit", title: "Audit log", body: "Track sensitive admin actions." },
  ];

  return (
    <div className="container mx-auto px-4 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Admin</h1>
        <p className="text-muted-foreground">Operate the platform.</p>
      </header>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {tiles.map((t) => (
          <Link key={t.href} href={t.href}>
            <Card className="h-full transition-shadow hover:shadow-md">
              <CardHeader>
                <CardTitle>{t.title}</CardTitle>
                <CardDescription>{t.body}</CardDescription>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </div>

      <Card className="mt-8">
        <CardHeader>
          <CardTitle>Search index</CardTitle>
          <CardDescription>
            Rebuild the search index from published courses. Runs in the background.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => reindex.mutate()} disabled={reindex.isPending}>
            <RefreshCw className={`mr-2 h-4 w-4 ${reindex.isPending ? "animate-spin" : ""}`} />
            {reindex.isPending ? "Queuing…" : "Reindex catalog"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
