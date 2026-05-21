export function SiteFooter() {
  return (
    <footer className="border-t bg-muted/30">
      <div className="container mx-auto flex flex-col items-center justify-between gap-4 px-4 py-6 text-sm text-muted-foreground sm:flex-row">
        <p>© {new Date().getFullYear()} Lumen. MIT licensed.</p>
        <nav className="flex gap-4">
          <a className="hover:text-foreground" href="/docs">
            Docs
          </a>
          <a className="hover:text-foreground" href="https://github.com/ahmedEid1/E-Learning-Platform">
            GitHub
          </a>
        </nav>
      </div>
    </footer>
  );
}
