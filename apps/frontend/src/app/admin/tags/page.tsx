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
    <div className="container mx-auto max-w-3xl px-4 py-14">
      <header className="mb-8 flex flex-col gap-3">
        <Cartouche>{t("adminTags.cartouche")}</Cartouche>
        <h1 className="font-display text-3xl font-medium tracking-tight">
          {t("adminTags.title")}
        </h1>
      </header>

      <Card className="scroll-paper border-gold/20">
        <CardHeader>
          <CardTitle className="font-display text-xl">{t("adminTags.addCard")}</CardTitle>
        </CardHeader>
        <CardContent>
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
              className="border-gold/25 bg-background/60 focus-visible:border-gold/60"
            />
            <Button type="submit" disabled={!name || create.isPending}>
              <Plus className="me-1 h-4 w-4" /> {t("adminTags.add")}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className="mt-6 scroll-paper border-gold/20">
        <CardHeader>
          <CardTitle className="font-display text-xl">{t("adminTags.allCard")}</CardTitle>
        </CardHeader>
        <CardContent>
          {!tagsQ.data?.length ? (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <Glyph name="feather" size={40} mode="tint" className="text-gold/40" />
              <p className="font-body italic text-muted-foreground">{t("adminTags.empty")}</p>
            </div>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {tagsQ.data.map((tag) => (
                <li
                  key={tag.id}
                  className="flex items-center gap-1.5 rounded-full border border-gold/25 bg-background/60 px-3 py-1 text-sm font-body transition-colors hover:border-gold/50"
                >
                  {tag.name}
                  <button
                    onClick={() => remove.mutate(tag.id)}
                    aria-label={t("studioEdit.remove")}
                    className="text-muted-foreground transition-colors hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
