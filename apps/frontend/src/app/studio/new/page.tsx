"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ImageUpload } from "@/components/shared/image-upload";
import { Catalog, Courses } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";

export default function NewCoursePage() {
  const router = useRouter();
  const { user, ready } = useAuth();
  const subjectsQ = useQuery({ queryKey: qk.subjects, queryFn: () => Catalog.subjects() });
  const [title, setTitle] = useState("");
  const [overview, setOverview] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [difficulty, setDifficulty] = useState("beginner");
  const [coverUrl, setCoverUrl] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (ready && (!user || user.role === "student")) router.replace("/login?next=/studio/new");
  }, [ready, user, router]);

  useEffect(() => {
    if (!subjectId && subjectsQ.data && subjectsQ.data.length > 0) {
      setSubjectId(subjectsQ.data[0].id);
    }
  }, [subjectId, subjectsQ.data]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const course = await Courses.create({
        title,
        subject_id: subjectId,
        overview,
        difficulty,
        ...(coverUrl ? { cover_url: coverUrl } : {}),
      });
      toast.success("Course created");
      router.push(`/studio/${course.id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not create course");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="container mx-auto max-w-2xl px-4 py-10">
      <Card>
        <CardHeader>
          <CardTitle>New course</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={submit}>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="title">
                Title
              </label>
              <Input id="title" required value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-sm font-medium" htmlFor="subject">
                  Subject
                </label>
                <select
                  id="subject"
                  className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                  value={subjectId}
                  onChange={(e) => setSubjectId(e.target.value)}
                  required
                >
                  {subjectsQ.data?.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.title}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium" htmlFor="difficulty">
                  Difficulty
                </label>
                <select
                  id="difficulty"
                  className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                  value={difficulty}
                  onChange={(e) => setDifficulty(e.target.value)}
                >
                  <option value="beginner">Beginner</option>
                  <option value="intermediate">Intermediate</option>
                  <option value="advanced">Advanced</option>
                </select>
              </div>
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="overview">
                Overview
              </label>
              <Textarea
                id="overview"
                rows={6}
                value={overview}
                onChange={(e) => setOverview(e.target.value)}
                placeholder="What will students learn?"
              />
            </div>
            <ImageUpload
              kind="cover"
              shape="rect"
              label="Cover image (optional)"
              value={coverUrl}
              onChange={setCoverUrl}
            />
            <Button type="submit" disabled={submitting || !subjectId}>
              {submitting ? "Creating…" : "Create course"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
