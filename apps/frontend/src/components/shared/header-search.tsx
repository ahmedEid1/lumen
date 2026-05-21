"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useT } from "@/lib/i18n/provider";

type Props = {
  /** Where to send the query. Defaults to /courses. */
  target?: string;
  className?: string;
};

export function HeaderSearch(props: Props) {
  // Wrap in Suspense because useSearchParams forces the closest non-
  // Suspended ancestor into dynamic rendering. The site header is mounted
  // on every route via layout.tsx, so we keep that boundary tight.
  return (
    <Suspense fallback={<HeaderSearchFallback className={props.className} />}>
      <HeaderSearchInner {...props} />
    </Suspense>
  );
}

function HeaderSearchFallback({ className }: { className?: string }) {
  return (
    <div className={className} aria-hidden>
      <div className="relative">
        <Search
          className="pointer-events-none absolute start-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          type="search"
          // Fallback renders during the dynamic-render Suspense window;
          // we don't have access to useT() here without a client-side
          // re-render, so the placeholder stays English. Visible for
          // microseconds; not worth the extra <ClientI18nGate>.
          placeholder="Search courses…"
          className="h-9 w-full ps-8 sm:w-56"
          disabled
        />
      </div>
    </div>
  );
}

function HeaderSearchInner({ target = "/courses", className }: Props) {
  const router = useRouter();
  const params = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const t = useT();

  // Keep the input in sync when the URL changes (e.g. when the catalog page
  // mounts already with a `q`).
  useEffect(() => {
    setQ(params.get("q") ?? "");
  }, [params]);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = q.trim();
    const url = trimmed ? `${target}?q=${encodeURIComponent(trimmed)}` : target;
    router.push(url);
  }

  return (
    <form role="search" onSubmit={onSubmit} className={className}>
      <label htmlFor="header-search" className="sr-only">
        {t("nav.search.placeholder")}
      </label>
      <div className="relative">
        <Search
          className="pointer-events-none absolute start-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          id="header-search"
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("nav.search.placeholder")}
          className="h-9 w-full ps-8 sm:w-56"
          enterKeyHint="search"
        />
      </div>
    </form>
  );
}
