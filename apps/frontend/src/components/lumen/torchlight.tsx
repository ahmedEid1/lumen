"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

/**
 * Torchlight — a soft gold radial that follows the cursor across the
 * section it wraps. Decorative only; pointer-events pass through.
 *
 * Implementation notes:
 *  - The element listens on its own bounding rect, so the effect is
 *    contained even on long pages.
 *  - Uses CSS custom props updated via rAF-throttled mousemove so we
 *    don't trigger React renders on every pixel.
 *  - On touch / no-hover devices we fall back to a static centred glow.
 */
export function Torchlight({
  className,
  intensity = 0.4,
}: {
  className?: string;
  intensity?: number;
}) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const supportsHover = window.matchMedia("(hover: hover)").matches;
    if (!supportsHover) return;

    let frame = 0;
    let next: { x: number; y: number } | null = null;

    function apply() {
      frame = 0;
      if (!el || !next) return;
      el.style.setProperty("--tx", `${next.x}%`);
      el.style.setProperty("--ty", `${next.y}%`);
    }

    const parent = el.parentElement;
    if (!parent) return;

    function onMove(e: MouseEvent) {
      const rect = parent!.getBoundingClientRect();
      next = {
        x: ((e.clientX - rect.left) / rect.width) * 100,
        y: ((e.clientY - rect.top) / rect.height) * 100,
      };
      if (!frame) frame = requestAnimationFrame(apply);
    }
    function onLeave() {
      el!.style.setProperty("--tx", `50%`);
      el!.style.setProperty("--ty", `50%`);
    }

    parent.addEventListener("mousemove", onMove);
    parent.addEventListener("mouseleave", onLeave);
    return () => {
      parent.removeEventListener("mousemove", onMove);
      parent.removeEventListener("mouseleave", onLeave);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div
      ref={ref}
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-0 -z-10 transition-opacity duration-700",
        className,
      )}
      style={{
        // initial position = centre; the rAF handler updates these.
        ["--tx" as string]: "50%",
        ["--ty" as string]: "50%",
        background: `radial-gradient(600px circle at var(--tx) var(--ty),
          hsl(var(--gold-leaf) / ${intensity}),
          hsl(var(--gold-leaf) / ${intensity * 0.4}) 22%,
          transparent 55%)`,
        animation: "torch-flicker 6s ease-in-out infinite",
      }}
    />
  );
}
