"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ImageUpload } from "@/components/shared/image-upload";
import { Catalog, Courses } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

/**
 * New course — Workbench repaint.
 *
 * Left-aligned label header, no centered marketing chrome. Form sits
 * directly on the page (no nested card frame) so the inputs stay the
 * focal point. Single lime primary CTA at the bottom.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */
export default function NewCoursePage() {
  const router = useRouter();
  const { user, ready } = useAuth();
  const t = useT();
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
      toast.success(t("studioNew.successToast"));
      router.push(`/studio/${course.id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("studioNew.error"));
    } finally {
      setSubmitting(false);
    }
  }

  const selectClass =
    "flex h-9 w-full rounded-md border border-border bg-muted px-3 py-2 font-body text-sm text-foreground transition-colors duration-[160ms] focus-visible:border-ring focus-visible:bg-background focus-visible:outline-none";

  return (
    <div className="container mx-auto max-w-2xl px-6 py-14">
      <header className="mb-8 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("studioNew.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("studioNew.title")}
        </h1>
      </header>

      <form className="space-y-5" onSubmit={submit}>
        <div className="space-y-1.5">
          <label className="font-body text-sm font-medium" htmlFor="title">
            {t("studioNew.field.title")}
          </label>
          <Input
            id="title"
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="font-body text-sm font-medium" htmlFor="subject">
              {t("studioNew.field.subject")}
            </label>
            <select
              id="subject"
              className={selectClass}
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
            <label className="font-body text-sm font-medium" htmlFor="difficulty">
              {t("studioNew.field.difficulty")}
            </label>
            <select
              id="difficulty"
              className={selectClass}
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value)}
            >
              <option value="beginner">{t("studioNew.diff.beginner")}</option>
              <option value="intermediate">{t("studioNew.diff.intermediate")}</option>
              <option value="advanced">{t("studioNew.diff.advanced")}</option>
            </select>
          </div>
        </div>
        <div className="space-y-1.5">
          <label className="font-body text-sm font-medium" htmlFor="overview">
            {t("studioNew.field.overview")}
          </label>
          <Textarea
            id="overview"
            rows={6}
            value={overview}
            onChange={(e) => setOverview(e.target.value)}
            placeholder={t("studioNew.placeholder.overview")}
          />
        </div>
        <ImageUpload
          kind="cover"
          shape="rect"
          label={t("studioNew.field.cover")}
          value={coverUrl}
          onChange={setCoverUrl}
        />
        <div className="pt-2">
          <Button type="submit" disabled={submitting || !subjectId}>
            {submitting ? t("studioNew.submitting") : t("studioNew.submit")}
          </Button>
        </div>
      </form>
    </div>
  );
}
