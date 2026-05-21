"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/lib/auth/store";

export default function AdminHome() {
  const { user, ready } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace("/login?next=/admin");
    else if (user.role !== "admin") router.replace("/dashboard");
  }, [ready, user, router]);
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
    </div>
  );
}
