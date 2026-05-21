"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { api } from "@/lib/api/client";
import { Catalog } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useT } from "@/lib/i18n/provider";

const inputClass = "border-gold/25 bg-background/60 focus-visible:border-gold/60";

export default function AdminSubjects() {
  const qc = useQueryClient();
  const t = useT();
  const subjectsQ = useQuery({ queryKey: qk.subjects, queryFn: () => Catalog.subjects() });
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api("/api/v1/admin/subjects", {
        method: "POST",
        body: { title, slug: slug || undefined },
      }),
    onSuccess: () => {
      toast.success(t("adminSubjects.successToast"));
      setTitle("");
      setSlug("");
      qc.invalidateQueries({ queryKey: qk.subjects });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("adminSubjects.addError")),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/v1/admin/subjects/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.subjects }),
    onError: (e: Error) => toast.error(e?.message ?? t("adminSubjects.deleteError")),
  });

  return (
    <div className="container mx-auto max-w-3xl px-4 py-14">
      <header className="mb-8 flex flex-col gap-3">
        <Cartouche>{t("adminSubjects.cartouche")}</Cartouche>
        <h1 className="font-display text-3xl font-medium tracking-tight">
          {t("adminSubjects.title")}
        </h1>
      </header>

      <Card className="scroll-paper border-gold/20">
        <CardHeader>
          <CardTitle className="font-display text-xl">{t("adminSubjects.addCard")}</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <Input
              placeholder={t("adminSubjects.titlePlaceholder")}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              className={inputClass}
            />
            <Input
              placeholder={t("adminSubjects.slugPlaceholder")}
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className={inputClass}
            />
            <Button type="submit" disabled={!title || create.isPending}>
              <Plus className="me-1 h-4 w-4" /> {t("adminTags.add")}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className="mt-6 scroll-paper border-gold/20">
        <CardHeader>
          <CardTitle className="font-display text-xl">{t("adminSubjects.allCard")}</CardTitle>
        </CardHeader>
        <CardContent>
          {!subjectsQ.data?.length ? (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <Glyph name="feather" size={40} mode="tint" className="text-gold/40" />
              <p className="font-body italic text-muted-foreground">{t("adminSubjects.empty")}</p>
            </div>
          ) : (
            <ul className="divide-y divide-gold/15">
              {subjectsQ.data.map((s) => (
                <li key={s.id} className="flex items-center justify-between py-3">
                  <div>
                    <div className="font-display text-base font-medium">{s.title}</div>
                    <div className="font-body text-xs text-muted-foreground">/{s.slug}</div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="font-body text-xs text-muted-foreground">
                      {t("adminSubjects.courseCount", { n: s.total_courses ?? 0 })}
                    </span>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => remove.mutate(s.id)}
                      aria-label={t("common.delete")}
                      className="text-muted-foreground transition-colors hover:text-destructive"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
