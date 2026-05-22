"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { Catalog } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useT } from "@/lib/i18n/provider";

/**
 * Admin tags — Workbench repaint.
 *
 * Flat add form, tags rendered as a bordered chip rail in mono. No
 * card chrome; chips inherit the surface utility's border treatment.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */
export default function AdminTags() {
  const qc = useQueryClient();
  const t = useT();
  const tagsQ = useQuery({ queryKey: qk.tags, queryFn: () => Catalog.tags() });
  const [name, setName] = useState("");

  const create = useMutation({
    mutationFn: () => api("/api/v1/admin/tags", { method: "POST", body: { name } }),
    onSuccess: () => {
      setName("");
      qc.invalidateQueries({ queryKey: qk.tags });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("adminTags.error")),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/v1/admin/tags/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.tags }),
  });

  return (
    <div className="container mx-auto max-w-3xl px-6 py-14">
      <header className="mb-8 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("adminTags.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("adminTags.title")}
        </h1>
      </header>

      <section className="mb-10 border-t border-border pt-6">
        <h2 className="mb-4 font-display text-base leading-tight tracking-tight">
          {t("adminTags.addCard")}
        </h2>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <Input
            placeholder={t("adminTags.namePlaceholder")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <Button type="submit" disabled={!name || create.isPending}>
            <Plus className="me-1 h-4 w-4" /> {t("adminTags.add")}
          </Button>
        </form>
      </section>

      <section className="border-t border-border pt-6">
        <h2 className="mb-4 font-display text-base leading-tight tracking-tight">
          {t("adminTags.allCard")}
        </h2>
        {!tagsQ.data?.length ? (
          <p className="font-body text-sm text-muted-foreground">{t("adminTags.empty")}</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {tagsQ.data.map((tag) => (
              <li
                key={tag.id}
                className="inline-flex items-center gap-2 rounded-md border border-border bg-muted px-2.5 py-1 font-mono text-xs uppercase tracking-wider text-muted-foreground transition-colors duration-[160ms] hover:border-foreground/40 hover:text-foreground"
              >
                {tag.name}
                <button
                  onClick={() => remove.mutate(tag.id)}
                  aria-label={t("studioEdit.remove")}
                  className="text-muted-foreground transition-colors duration-[160ms] hover:text-destructive"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
