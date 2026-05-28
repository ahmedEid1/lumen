"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { Catalog } from "@/lib/api/endpoints";
import type { SubjectOut } from "@/lib/api/types";
import { qk } from "@/lib/query/keys";
import { useT, useTN } from "@/lib/i18n/provider";

/**
 * Admin subjects — Workbench repaint.
 *
 * Flat add form on the page background, list rendered as a hairline-
 * divided list — no nested card chrome. Slugs and counts in mono so
 * the columns scan cleanly.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */
export default function AdminSubjects() {
  const qc = useQueryClient();
  const t = useT();
  const tn = useTN();
  const subjectsQ = useQuery({ queryKey: qk.subjects, queryFn: () => Catalog.subjects() });
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  // Inline rename: which subject row is open for edit, and its draft title.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");

  const startEdit = (s: SubjectOut) => {
    setEditingId(s.id);
    setEditTitle(s.title);
  };
  const cancelEdit = () => {
    setEditingId(null);
    setEditTitle("");
  };

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
  const rename = useMutation({
    mutationFn: (vars: { id: string; title: string }) =>
      api<SubjectOut>(`/api/v1/admin/subjects/${vars.id}`, {
        method: "PATCH",
        body: { title: vars.title },
      }),
    onSuccess: () => {
      toast.success(t("adminSubjects.renameSuccess"));
      cancelEdit();
      qc.invalidateQueries({ queryKey: qk.subjects });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("adminSubjects.renameError")),
  });

  return (
    <div className="container mx-auto max-w-3xl px-6 py-14">
      <header className="mb-8 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("adminSubjects.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("adminSubjects.title")}
        </h1>
      </header>

      <section className="mb-10 border-t border-border pt-6">
        <h2 className="mb-4 font-display text-base leading-tight tracking-tight">
          {t("adminSubjects.addCard")}
        </h2>
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
          />
          <Input
            placeholder={t("adminSubjects.slugPlaceholder")}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
          <Button type="submit" disabled={!title || create.isPending}>
            <Plus className="me-1 h-4 w-4" /> {t("adminTags.add")}
          </Button>
        </form>
      </section>

      <section className="border-t border-border pt-6">
        <h2 className="mb-4 font-display text-base leading-tight tracking-tight">
          {t("adminSubjects.allCard")}
        </h2>
        {!subjectsQ.data?.length ? (
          <p className="font-body text-sm text-muted-foreground">{t("adminSubjects.empty")}</p>
        ) : (
          <ul className="divide-y divide-border border-y border-border">
            {subjectsQ.data.map((s) => (
              <li
                key={s.id}
                className="flex items-center justify-between gap-3 px-1 py-3 transition-colors duration-[160ms] hover:bg-muted/30"
              >
                {editingId === s.id ? (
                  <form
                    className="flex flex-1 items-center gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      rename.mutate({ id: s.id, title: editTitle });
                    }}
                  >
                    <Input
                      autoFocus
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      aria-label={t("adminSubjects.renameAria")}
                      className="h-8"
                      required
                    />
                    <Button
                      type="submit"
                      variant="ghost"
                      size="icon"
                      disabled={!editTitle.trim() || rename.isPending}
                      aria-label={t("common.save")}
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <Check className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={cancelEdit}
                      aria-label={t("common.cancel")}
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </form>
                ) : (
                  <>
                    <div>
                      <div className="font-body text-sm font-medium text-foreground">{s.title}</div>
                      <div className="font-mono text-xs text-muted-foreground">/{s.slug}</div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-xs tabular-nums text-muted-foreground">
                        {tn("adminSubjects.courseCount", s.total_courses ?? 0)}
                      </span>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => startEdit(s)}
                        aria-label={t("adminSubjects.renameAria")}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => remove.mutate(s.id)}
                        aria-label={t("common.delete")}
                        className="text-muted-foreground hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
