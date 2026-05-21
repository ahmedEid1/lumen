"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";

type Props = {
  /** Where to send the query. Defaults to /courses. */
  target?: string;
  className?: string;
};

export function HeaderSearch({ target = "/courses", className }: Props) {
  const router = useRouter();
  const params = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");

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
        Search courses
      </label>
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          id="header-search"
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search courses…"
          className="h-9 w-full pl-8 sm:w-56"
          enterKeyHint="search"
        />
      </div>
    </form>
  );
}
