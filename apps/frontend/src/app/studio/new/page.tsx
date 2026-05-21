"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ImageUpload } from "@/components/shared/image-upload";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { Catalog, Courses } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

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

  const inputClass = "border-gold/25 bg-background/60 focus-visible:border-gold/60";
  const selectClass = `${inputClass} h-10 w-full rounded-md border px-3 font-body text-sm`;

  return (
    <div className="container mx-auto flex max-w-2xl flex-col items-center px-4 py-14">
      <Cartouche className="mb-5">{t("studioNew.cartouche")}</Cartouche>
      <Card className="w-full scroll-paper border-gold/20">
        <CardContent className="space-y-6 pt-8">
          <header className="flex flex-col items-center gap-3 text-center">
            <Glyph
              name="feather"
              size={42}
              mode="tint"
              className="text-gold/85 drop-shadow-[0_0_10px_hsl(var(--gold-leaf)/0.4)]"
            />
            <h1 className="font-display text-3xl font-medium tracking-tight">
              {t("studioNew.title")}
            </h1>
          </header>

          <form className="space-y-4" onSubmit={submit}>
            <div className="space-y-1.5">
              <label className="font-body text-sm font-medium" htmlFor="title">
                {t("studioNew.field.title")}
              </label>
              <Input
                id="title"
                required
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className={inputClass}
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
                className={inputClass}
              />
            </div>
            <ImageUpload
              kind="cover"
              shape="rect"
              label={t("studioNew.field.cover")}
              value={coverUrl}
              onChange={setCoverUrl}
            />
            <Button type="submit" className="w-full" disabled={submitting || !subjectId}>
              {submitting ? t("studioNew.submitting") : t("studioNew.submit")}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
