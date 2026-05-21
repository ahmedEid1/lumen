import { cn } from "@/lib/utils";

/**
 * Cartouche — gold-edged oval frame that encloses a name in an
 * Egyptian inscription. Used here as a section eyebrow / kicker
 * that signals "this is a named, important place in the document".
 *
 * Visually: two rounded vertical caps + a thin horizontal terminator
 * line, all rendered in gold. The children sit centred in small caps.
 */
export function Cartouche({
  children,
  className,
  as: Tag = "p",
}: {
  children: React.ReactNode;
  className?: string;
  as?: React.ElementType;
}) {
  return (
    <Tag
      className={cn(
        "inline-flex items-center gap-3 text-[0.7rem] uppercase tracking-[0.32em]",
        "font-medium text-gold/90",
        className,
      )}
    >
      <span aria-hidden className="flex items-center">
        <span className="block h-px w-10 bg-gradient-to-r from-transparent to-gold/70" />
        <span className="ml-1 block h-1.5 w-1.5 rounded-full bg-gold/80 shadow-[0_0_10px_2px_hsl(var(--gold-leaf)/0.5)]" />
      </span>
      <span>{children}</span>
      <span aria-hidden className="flex items-center">
        <span className="block h-1.5 w-1.5 rounded-full bg-gold/80 shadow-[0_0_10px_2px_hsl(var(--gold-leaf)/0.5)]" />
        <span className="ml-1 block h-px w-10 bg-gradient-to-l from-transparent to-gold/70" />
      </span>
    </Tag>
  );
}
