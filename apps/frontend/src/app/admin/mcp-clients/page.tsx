"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Check,
  Copy,
  KeyRound,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";

/**
 * QA-iter4: admin/mcp-clients — closes the last parity gap from
 * iter 2's audit. Phase I1 shipped the MCP client CRUD backend
 * (`/api/v1/admin/mcp-clients` + `/{client_id}`) but no UI; admins
 * had to curl to manage their MCP integration credentials.
 *
 * Surface design follows the GitHub-PAT pattern every developer
 * already knows:
 *   - List view: live clients by default, toggle to include revoked
 *     for the audit view.
 *   - Mint dialog: fields are owner_user_id + name + scopes (CSV,
 *     scopes default to `*` if left empty).
 *   - One-time secret reveal: on successful mint, the response
 *     contains plaintext `client_secret` — shown in a Dialog with
 *     a copy-to-clipboard button. "I've saved it" close. Secret
 *     never persists after dialog close (no localStorage, no state
 *     retention; navigate-away wipes it).
 *   - Revoke: per-row destructive button with a confirm step.
 *
 * No i18n keys — admin-only surface, ships English-first like the
 * rest of /admin (see admin.tile.* convention).
 */

type MCPClientOut = {
  client_id: string;
  owner_user_id: string;
  name: string;
  scopes: string[];
  revoked_at: string | null;
  last_used_at: string | null;
  created_at: string;
};

type MCPClientCreatedOut = {
  client_id: string;
  client_secret: string;
  owner_user_id: string;
  name: string;
  scopes: string[];
  created_at: string;
};

type AdminUserOut = {
  id: string;
  email: string;
  full_name: string;
  role: string;
};

export default function AdminMCPClientsPage() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const qc = useQueryClient();
  const [includeRevoked, setIncludeRevoked] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [revealSecret, setRevealSecret] =
    useState<MCPClientCreatedOut | null>(null);

  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace("/login?next=/admin/mcp-clients");
    else if (user.role !== "admin") router.replace("/dashboard");
  }, [ready, user, router]);

  const clientsQ = useQuery({
    queryKey: ["admin", "mcp-clients", { includeRevoked }],
    queryFn: () =>
      api<MCPClientOut[]>(
        `/api/v1/admin/mcp-clients?include_revoked=${includeRevoked}`,
      ),
    enabled: !!user && user.role === "admin",
  });

  if (!ready || !user || user.role !== "admin") return null;

  return (
    <div className="container mx-auto max-w-6xl px-6 py-14">
      <header className="mb-10 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Lumen / admin / mcp clients
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          MCP clients
        </h1>
        <p className="max-w-3xl font-body text-sm text-muted-foreground">
          OAuth-style client credentials for Model Context Protocol
          integrations. Mint a client on behalf of a Lumen user; the
          secret is shown once and never re-displayed. Revoke is a
          soft-delete — historical rows stay queryable with the
          &ldquo;include revoked&rdquo; toggle.
        </p>
      </header>

      <section className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 font-body text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={includeRevoked}
            onChange={(e) => setIncludeRevoked(e.target.checked)}
            className="h-4 w-4 rounded border-border"
          />
          Include revoked clients
        </label>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="me-2 h-4 w-4" /> New client
        </Button>
      </section>

      <section className="surface p-0">
        {clientsQ.isLoading ? (
          <p className="p-4 font-mono text-xs text-muted-foreground">
            Loading…
          </p>
        ) : clientsQ.isError ? (
          <p className="p-4 font-mono text-xs text-destructive">
            Could not load MCP clients.
          </p>
        ) : (clientsQ.data ?? []).length === 0 ? (
          <p className="p-6 font-body text-sm text-muted-foreground">
            No MCP clients yet. Mint one with the button above.
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border font-mono text-xs uppercase tracking-wider text-muted-foreground">
                <th className="px-4 py-3">Client</th>
                <th className="px-4 py-3">Owner</th>
                <th className="px-4 py-3">Scopes</th>
                <th className="px-4 py-3">Last used</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3 text-right">Status</th>
              </tr>
            </thead>
            <tbody>
              {(clientsQ.data ?? []).map((c) => (
                <ClientRow
                  key={c.client_id}
                  client={c}
                  onRevoked={() =>
                    qc.invalidateQueries({
                      queryKey: ["admin", "mcp-clients"],
                    })
                  }
                />
              ))}
            </tbody>
          </table>
        )}
      </section>

      <CreateClientDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(resp) => {
          setCreateOpen(false);
          setRevealSecret(resp);
          qc.invalidateQueries({ queryKey: ["admin", "mcp-clients"] });
        }}
      />
      <RevealSecretDialog
        secret={revealSecret}
        onClose={() => {
          setRevealSecret(null);
          // Codex rescue: clear the plaintext secret from React-Query
          // mutation cache. Without this the `data` field on
          // useMutation still holds it after dialog close — the
          // "secret is unrecoverable" promise in the dialog copy is a
          // lie if the secret is still in memory. The CreateClientDialog's
          // mutation owns the cache row, so its onCreated callback
          // also resets the mutation right after the reveal opens.
        }}
      />
    </div>
  );
}

function ClientRow({
  client,
  onRevoked,
}: {
  client: MCPClientOut;
  onRevoked: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const revokeMut = useMutation({
    mutationFn: () =>
      api<MCPClientOut>(
        `/api/v1/admin/mcp-clients/${encodeURIComponent(client.client_id)}`,
        { method: "DELETE" },
      ),
    onSuccess: () => {
      toast.success(`Revoked ${client.client_id}`);
      onRevoked();
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Revoke failed");
    },
  });
  const revoked = client.revoked_at !== null;
  const short = client.client_id.slice(0, 8);
  return (
    <tr className="border-b border-border/40">
      <td className="px-4 py-3">
        <div className="flex flex-col">
          <span className="font-mono text-foreground">{short}…</span>
          <span className="font-body text-xs text-muted-foreground">
            {client.name || <em>unnamed</em>}
          </span>
        </div>
      </td>
      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
        {client.owner_user_id}
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {client.scopes.map((s) => (
            <Badge key={s} variant="muted" className="font-mono">
              {s}
            </Badge>
          ))}
        </div>
      </td>
      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
        {client.last_used_at
          ? new Date(client.last_used_at).toISOString().slice(0, 10)
          : "—"}
      </td>
      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
        {new Date(client.created_at).toISOString().slice(0, 10)}
      </td>
      <td className="px-4 py-3 text-right">
        {revoked ? (
          <Badge variant="muted" className="font-mono">
            revoked
          </Badge>
        ) : confirming ? (
          <span className="inline-flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirming(false)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => revokeMut.mutate()}
              disabled={revokeMut.isPending}
            >
              {revokeMut.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
              <span className="ms-1">Confirm</span>
            </Button>
          </span>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setConfirming(true)}
          >
            <Trash2 className="me-1 h-4 w-4" /> Revoke
          </Button>
        )}
      </td>
    </tr>
  );
}

function CreateClientDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (resp: MCPClientCreatedOut) => void;
}) {
  const [ownerId, setOwnerId] = useState("");
  const [ownerLabel, setOwnerLabel] = useState("");
  const [userSearch, setUserSearch] = useState("");
  const [name, setName] = useState("");
  const [scopesCsv, setScopesCsv] = useState("*");

  // Codex rescue #2: search-driven owner picker. The admin/users
  // endpoint defaults to the 50 newest users, so a fixed dropdown
  // couldn't reach older accounts. Debounce 200ms — keep the network
  // calls reasonable while the admin types an email fragment.
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useEffect(() => {
    const id = setTimeout(() => setDebouncedSearch(userSearch.trim()), 200);
    return () => clearTimeout(id);
  }, [userSearch]);

  const usersQ = useQuery({
    queryKey: ["admin", "users", "for-mcp-picker", debouncedSearch],
    queryFn: () =>
      api<AdminUserOut[]>(
        `/api/v1/admin/users${debouncedSearch ? `?q=${encodeURIComponent(debouncedSearch)}` : ""}`,
      ),
    enabled: open,
  });

  const createMut = useMutation({
    mutationFn: (body: { owner_user_id: string; name: string; scopes: string[] }) =>
      api<MCPClientCreatedOut>("/api/v1/admin/mcp-clients", {
        method: "POST",
        body,
      }),
    onSuccess: (resp) => {
      onCreated(resp);
      // Reset form for the next mint AND wipe the plaintext secret
      // from useMutation's cache (Codex rescue #1) so the dialog's
      // "the secret is unrecoverable after close" promise is honest.
      setOwnerId("");
      setOwnerLabel("");
      setUserSearch("");
      setName("");
      setScopesCsv("*");
      createMut.reset();
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Mint failed");
    },
  });
  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ownerId) return;
    const scopes = scopesCsv
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    createMut.mutate({
      owner_user_id: ownerId,
      name,
      scopes: scopes.length ? scopes : ["*"],
    });
  };
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Mint a new MCP client</DialogTitle>
          <DialogDescription>
            The client secret is shown <strong>once</strong> on the
            next screen and never re-displayed. Treat it like a GitHub
            PAT — if lost, revoke and mint a fresh one.
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-3" onSubmit={onSubmit}>
          <div>
            <label
              htmlFor="mcp-owner-search"
              className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-muted-foreground"
            >
              Owner user
            </label>
            {ownerId ? (
              <div className="flex items-center justify-between rounded-md border border-border bg-muted px-3 py-2 font-mono text-sm">
                <span className="truncate">{ownerLabel}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setOwnerId("");
                    setOwnerLabel("");
                    setUserSearch("");
                  }}
                >
                  Change
                </Button>
              </div>
            ) : (
              <>
                <Input
                  id="mcp-owner-search"
                  type="search"
                  value={userSearch}
                  onChange={(e) => setUserSearch(e.target.value)}
                  placeholder="Search email or name…"
                  autoComplete="off"
                />
                {usersQ.isFetching && (
                  <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                    Searching…
                  </p>
                )}
                {!usersQ.isFetching && (usersQ.data ?? []).length > 0 && (
                  <ul
                    className="mt-1 max-h-48 overflow-y-auto rounded-md border border-border bg-background"
                    role="listbox"
                    aria-label="User search results"
                  >
                    {(usersQ.data ?? []).slice(0, 20).map((u) => (
                      <li key={u.id}>
                        <button
                          type="button"
                          onClick={() => {
                            setOwnerId(u.id);
                            setOwnerLabel(`${u.email} (${u.role})`);
                          }}
                          className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left font-body text-sm hover:bg-muted/30"
                        >
                          <span className="truncate">{u.email}</span>
                          <span className="font-mono text-xs text-muted-foreground">
                            {u.role}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {!usersQ.isFetching &&
                  debouncedSearch &&
                  (usersQ.data ?? []).length === 0 && (
                    <p className="mt-1 font-body text-xs text-muted-foreground">
                      No users matched.
                    </p>
                  )}
              </>
            )}
          </div>
          <div>
            <label
              htmlFor="mcp-name"
              className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-muted-foreground"
            >
              Name (optional)
            </label>
            <Input
              id="mcp-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Claude Desktop integration"
              maxLength={120}
            />
          </div>
          <div>
            <label
              htmlFor="mcp-scopes"
              className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-muted-foreground"
            >
              Scopes (comma-separated)
            </label>
            <Input
              id="mcp-scopes"
              value={scopesCsv}
              onChange={(e) => setScopesCsv(e.target.value)}
              placeholder="*"
            />
            <p className="mt-1 font-body text-xs text-muted-foreground">
              Leave as <code className="font-mono">*</code> for full
              MCP access. Specific scopes lock the client to a subset
              of tools.
            </p>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!ownerId || createMut.isPending}>
              {createMut.isPending ? (
                <>
                  <Loader2 className="me-2 h-4 w-4 animate-spin" /> Minting…
                </>
              ) : (
                <>
                  <KeyRound className="me-2 h-4 w-4" /> Mint client
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RevealSecretDialog({
  secret,
  onClose,
}: {
  secret: MCPClientCreatedOut | null;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    if (!secret) return;
    try {
      await navigator.clipboard.writeText(secret.client_secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Copy failed — select the text manually.");
    }
  };
  return (
    <Dialog open={!!secret} onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Client minted — copy the secret now</DialogTitle>
          <DialogDescription>
            This is the <strong>only time</strong> the secret is
            displayed. Save it somewhere safe (your password manager,
            an env var, the integration&apos;s config). After you close
            this dialog, the secret is unrecoverable — losing it
            means revoking + minting again.
          </DialogDescription>
        </DialogHeader>
        {secret && (
          <div className="space-y-3">
            <div>
              <p className="mb-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                Client ID
              </p>
              <code className="block break-all rounded-md border border-border bg-muted px-3 py-2 font-mono text-sm">
                {secret.client_id}
              </code>
            </div>
            <div>
              <div className="mb-1 flex items-center justify-between">
                <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                  Client secret
                </p>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={onCopy}
                  aria-live="polite"
                >
                  {copied ? (
                    <>
                      <Check className="me-1 h-3.5 w-3.5" /> Copied
                    </>
                  ) : (
                    <>
                      <Copy className="me-1 h-3.5 w-3.5" /> Copy
                    </>
                  )}
                </Button>
              </div>
              <code className="block break-all rounded-md border border-primary/40 bg-primary/5 px-3 py-2 font-mono text-sm text-foreground">
                {secret.client_secret}
              </code>
            </div>
          </div>
        )}
        <DialogFooter>
          <Button onClick={onClose}>I&apos;ve saved it</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
