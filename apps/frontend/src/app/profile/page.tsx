"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, Download } from "lucide-react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { ImageUpload } from "@/components/shared/image-upload";
import { SessionsCard } from "@/components/shared/sessions-card";
import { api } from "@/lib/api/client";
import {
  Me,
  Users,
  type NotificationDispatch,
  type NotificationKind,
} from "@/lib/api/endpoints";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import { useReturnFocus } from "@/lib/a11y/use-return-focus";

// Fallback + display-order only — the rendered form is driven by the keys
// `GET /prefs` returns (which materialises the full backend enum), so a new
// backend kind can never silently drop out of the form again (the P2.8
// drift: `course_cloned` fired in prod for months while this hardcoded
// list hid it from the prefs UI).
const NOTIFICATION_KINDS: NotificationKind[] = [
  "enrolled",
  "lesson_available",
  "certificate_ready",
  "review_received",
  "chat_mention",
  "security",
  "discussion_reply",
  "course_cloned",
];

const DISPATCH_OPTIONS: NotificationDispatch[] = [
  "off",
  "in_app",
  "email_immediate",
  "digest_daily",
];

/** i18n label for a kind, falling back to the raw kind string for a server
 * kind that doesn't have a translation yet (t() echoes the key when the
 * entry is missing — render something honest rather than the raw key). */
function kindLabel(t: ReturnType<typeof useT>, kind: string): string {
  const key = `prefs.notifications.kind.${kind}`;
  const label = t(key as Parameters<typeof t>[0]);
  return label === key ? kind.replaceAll("_", " ") : label;
}

/**
 * Profile — Workbench repaint.
 *
 * Stacked sections separated by `border-t border-border` (profile,
 * password, email, sessions, delete account). No nested card chrome
 * around the forms — labels carry the structure. Destructive section
 * gets `border-destructive/30 bg-destructive/5` and lives at the
 * bottom; the destructive CTA is the only red affordance on the page.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */
export default function ProfilePage() {
  const { user, ready, refresh, logout } = useAuth();
  const router = useRouter();
  const qc = useQueryClient();
  const t = useT();
  const [fullName, setFullName] = useState("");
  const [bio, setBio] = useState("");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);

  const [currentPwd, setCurrentPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [savingPwd, setSavingPwd] = useState(false);

  const [newEmail, setNewEmail] = useState("");
  const [emailPwd, setEmailPwd] = useState("");
  const [requestingEmail, setRequestingEmail] = useState(false);

  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deletePwd, setDeletePwd] = useState("");
  // Type-to-confirm gate (S6.11 / FR-A11Y-05): the user must type the confirm
  // word AND supply their password before the destructive button arms.
  const [deleteWord, setDeleteWord] = useState("");
  const [deleting, setDeleting] = useState(false);
  // Delete-confirmation Dialog is controlled (no <DialogTrigger>) —
  // restore focus to the "Delete account" button on close (WCAG 2.4.3).
  const onDeleteCloseAutoFocus = useReturnFocus(confirmDelete);

  // Notification preferences (Phase D4). Loaded once on mount and kept
  // in local state; saved as a whole-form PUT — the backend treats the
  // payload as a partial merge, but the UI presents every kind at
  // once so submitting all of them is simpler and avoids a confused
  // "only some toggles saved" state if the user picks several.
  const [notifPrefs, setNotifPrefs] = useState<Record<
    NotificationKind,
    NotificationDispatch
  > | null>(null);
  const [savingPrefs, setSavingPrefs] = useState(false);

  useEffect(() => {
    if (ready && !user) router.replace("/login?next=/profile");
  }, [ready, user, router]);

  useEffect(() => {
    if (user) {
      setFullName(user.full_name ?? "");
      setBio(user.bio ?? "");
      setAvatarUrl(user.avatar_url ?? "");
    }
  }, [user]);

  // Fetch current notification dispatch prefs once the user is loaded.
  // Defaults to ``in_app`` server-side, so a fresh account renders the
  // form with every kind preselected to "Bell only".
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await Me.notificationPrefs.get();
        if (!cancelled) setNotifPrefs(res.prefs);
      } catch {
        if (!cancelled) {
          // Fall back to local defaults so the form is still usable
          // if the GET fails — the PUT will create stored state.
          const fallback = NOTIFICATION_KINDS.reduce(
            (acc, k) => ({ ...acc, [k]: "in_app" as NotificationDispatch }),
            {} as Record<NotificationKind, NotificationDispatch>,
          );
          setNotifPrefs(fallback);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  if (!ready || !user) return null;

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    setSavingProfile(true);
    try {
      await api("/api/v1/users/me", {
        method: "PATCH",
        body: { full_name: fullName, bio, avatar_url: avatarUrl || null },
      });
      toast.success(t("profile.toast.saved"));
      await refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("profile.toast.saveError"));
    } finally {
      setSavingProfile(false);
    }
  }

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    setSavingPwd(true);
    try {
      await api("/api/v1/users/me/change-password", {
        method: "POST",
        body: { current_password: currentPwd, new_password: newPwd },
      });
      toast.success(t("profile.toast.passwordChanged"));
      setCurrentPwd("");
      setNewPwd("");
      await logout();
      router.push("/login");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("profile.toast.passwordError"));
    } finally {
      setSavingPwd(false);
    }
  }

  async function requestEmailChange(e: React.FormEvent) {
    e.preventDefault();
    setRequestingEmail(true);
    try {
      await api("/api/v1/users/me/email/request", {
        method: "POST",
        body: { new_email: newEmail, current_password: emailPwd },
      });
      toast.success(t("profile.toast.emailChangeSent", { email: newEmail }));
      setNewEmail("");
      setEmailPwd("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("profile.toast.emailError"));
    } finally {
      setRequestingEmail(false);
    }
  }

  async function saveNotifPrefs(e: React.FormEvent) {
    e.preventDefault();
    if (!notifPrefs) return;
    setSavingPrefs(true);
    try {
      const res = await Me.notificationPrefs.update(notifPrefs);
      setNotifPrefs(res.prefs);
      toast.success(t("prefs.notifications.savedToast"));
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : t("prefs.notifications.errorToast"),
      );
    } finally {
      setSavingPrefs(false);
    }
  }

  async function deleteAccount() {
    setDeleting(true);
    try {
      // S6.8 anonymize-in-place: scrub PII, purge sessions, delist owned
      // courses, all in one transaction server-side.
      await Users.deleteMe(deletePwd);
      toast.success(t("profile.toast.deleted"));
      // Wipe every cached query so no stale authed data lingers, tear down the
      // session, then hard-redirect home (a full navigation, not a client push,
      // so the app boots fresh as an anonymous visitor).
      qc.clear();
      await logout();
      window.location.assign("/");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("profile.toast.deleteError"));
      setDeleting(false);
    }
  }

  return (
    <div className="container mx-auto max-w-3xl px-6 py-14">
      {/* Identity header */}
      <header className="mb-10 flex flex-col gap-4">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("profile.cartouche")}
        </p>
        <div className="flex items-center gap-5">
          <Avatar className="h-16 w-16 border border-border">
            <AvatarImage src={user.avatar_url ?? undefined} alt={user.full_name} />
            <AvatarFallback className="bg-muted text-xl font-medium text-foreground">
              {user.full_name.slice(0, 1).toUpperCase() || "U"}
            </AvatarFallback>
          </Avatar>
          <div className="flex flex-col gap-1.5">
            <h1 className="font-display text-2xl leading-tight tracking-tight sm:text-3xl">
              {user.full_name || user.email}
            </h1>
            <div className="flex flex-wrap items-center gap-2 font-mono text-xs text-muted-foreground">
              <span>{user.email}</span>
              <Badge variant="muted">{user.role}</Badge>
              {user.email_verified_at ? (
                <Badge>{t("profile.badge.verified")}</Badge>
              ) : (
                <Badge variant="destructive">{t("profile.badge.unverified")}</Badge>
              )}
            </div>
          </div>
        </div>
      </header>

      {!user.email_verified_at && (
        <div className="mb-10 flex flex-col items-start justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm sm:flex-row sm:items-center">
          <p className="flex items-center gap-2 font-body text-destructive">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            {t("profile.banner.unverified")}
          </p>
          <Button
            size="sm"
            variant="outline"
            onClick={async () => {
              try {
                await api("/api/v1/auth/verify/request", { method: "POST" });
                toast.success(t("profile.toast.verifyResent"));
              } catch (e) {
                toast.error(e instanceof Error ? e.message : t("profile.toast.verifyError"));
              }
            }}
          >
            {t("profile.banner.resend")}
          </Button>
        </div>
      )}

      {/* Profile section */}
      <Section
        title={t("profile.section.profile")}
        description={t("profile.section.profileDesc")}
      >
        <form className="space-y-4" onSubmit={saveProfile}>
          <div className="space-y-1.5">
            <label htmlFor="full_name" className="font-body text-sm font-medium">
              {t("auth.register.fullName")}
            </label>
            <Input
              id="full_name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="bio" className="font-body text-sm font-medium">
              {t("profile.field.bio")}
            </label>
            <Textarea
              id="bio"
              rows={4}
              value={bio}
              onChange={(e) => setBio(e.target.value)}
            />
          </div>
          <ImageUpload
            kind="avatar"
            shape="circle"
            label={t("profile.field.avatar")}
            value={avatarUrl || null}
            onChange={(u) => setAvatarUrl(u ?? "")}
          />
          <Button type="submit" disabled={savingProfile}>
            {savingProfile ? t("common.saving") : t("profile.save")}
          </Button>
        </form>
      </Section>

      {/* Password section */}
      <Section
        title={t("profile.section.password")}
        description={t("profile.section.passwordDesc")}
      >
        <form className="space-y-4" onSubmit={changePassword}>
          {/* Hidden username field: password managers + screen readers expect
              a username adjacent to password inputs so the credential is
              associated with the right account (Chrome a11y audit). */}
          <input
            type="text"
            name="username"
            autoComplete="username"
            value={user.email}
            readOnly
            tabIndex={-1}
            aria-hidden="true"
            className="sr-only"
          />
          <Input
            type="password"
            placeholder={t("profile.field.currentPassword")}
            value={currentPwd}
            onChange={(e) => setCurrentPwd(e.target.value)}
            autoComplete="current-password"
            required
          />
          <Input
            type="password"
            placeholder={t("profile.field.newPasswordPlaceholder")}
            value={newPwd}
            onChange={(e) => setNewPwd(e.target.value)}
            autoComplete="new-password"
            minLength={12}
            required
          />
          <Button type="submit" disabled={savingPwd}>
            {savingPwd ? t("profile.password.submitting") : t("profile.password.submit")}
          </Button>
        </form>
      </Section>

      {/* Email section */}
      <Section
        title={t("profile.section.email")}
        description={t("profile.section.emailDesc")}
      >
        <form className="space-y-4" onSubmit={requestEmailChange}>
          <div className="space-y-1.5">
            <label htmlFor="current_email" className="font-body text-sm font-medium">
              {t("profile.field.currentEmail")}
            </label>
            <Input id="current_email" value={user.email} disabled />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="new_email" className="font-body text-sm font-medium">
              {t("profile.field.newEmail")}
            </label>
            <Input
              id="new_email"
              type="email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              autoComplete="email"
              required
            />
          </div>
          <Input
            type="password"
            placeholder={t("profile.field.currentPassword")}
            value={emailPwd}
            onChange={(e) => setEmailPwd(e.target.value)}
            autoComplete="current-password"
            required
          />
          <Button type="submit" disabled={requestingEmail || !newEmail || !emailPwd}>
            {requestingEmail ? t("profile.email.submitting") : t("profile.email.submit")}
          </Button>
        </form>
      </Section>

      {/* Notification preferences (Phase D4) */}
      <Section
        title={t("prefs.notifications.title")}
        description={t("prefs.notifications.description")}
      >
        <form className="space-y-4" onSubmit={saveNotifPrefs}>
          {notifPrefs == null ? (
            <p className="font-body text-sm text-muted-foreground">
              {t("common.loading")}
            </p>
          ) : (
            <>
              <div className="divide-y divide-border rounded-md border border-border">
                {(Object.keys(notifPrefs) as NotificationKind[])
                  .sort((a, b) => {
                    // Canonical order first; server kinds we don't know yet
                    // (future enum additions) sort to the end instead of
                    // disappearing.
                    const ia = NOTIFICATION_KINDS.indexOf(a);
                    const ib = NOTIFICATION_KINDS.indexOf(b);
                    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
                  })
                  .map((kind) => (
                  <div
                    key={kind}
                    className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <label
                      htmlFor={`pref-${kind}`}
                      className="font-body text-sm font-medium"
                    >
                      {kindLabel(t, kind)}
                    </label>
                    <Select
                      value={notifPrefs[kind] ?? "in_app"}
                      onValueChange={(v) =>
                        setNotifPrefs((prev) =>
                          prev
                            ? {
                                ...prev,
                                [kind]: v as NotificationDispatch,
                              }
                            : prev,
                        )
                      }
                    >
                      <SelectTrigger id={`pref-${kind}`} className="sm:w-48">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {DISPATCH_OPTIONS.map((opt) => (
                          <SelectItem key={opt} value={opt}>
                            {t(`prefs.notifications.dispatch.${opt}`)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ))}
              </div>
              <Button type="submit" disabled={savingPrefs}>
                {savingPrefs
                  ? t("prefs.notifications.saving")
                  : t("prefs.notifications.save")}
              </Button>
            </>
          )}
        </form>
      </Section>

      {/* Data export — QA-iter2 wires the /api/v1/users/me/export
          endpoint that was shipped without a UI. The endpoint returns
          a JSON blob with the user's profile + counts of enrollments
          / reviews; future enhancement (per the backend docstring)
          enqueues a Celery job that produces a full zip. The button
          downloads the current JSON via a blob so a privacy-curious
          user has a working "download my data" affordance today.
          QA-iter6: moved above SessionsCard — the active sessions list
          can be 50 rows long for power users, which was pushing the
          Export affordance below the fold of any reasonable scroll. */}
      <section className="mb-10 border-t border-border pt-8">
        <ExportDataCard />
      </section>

      {/* Sessions card — keeps its own surface */}
      <section className="mb-10 border-t border-border pt-8">
        <SessionsCard />
      </section>

      {/* Danger zone — bordered destructive surface */}
      <section className="rounded-md border border-destructive/30 bg-destructive/5 p-5">
        <h2 className="font-display text-lg leading-tight tracking-tight text-destructive">
          {t("profile.section.delete")}
        </h2>
        <p className="mt-1 font-body text-sm text-muted-foreground">
          {t("profile.section.deleteDesc")}
        </p>
        <div className="mt-4">
          <Button variant="destructive" onClick={() => setConfirmDelete(true)}>
            {t("profile.delete.button")}
          </Button>
        </div>
      </section>

      <Dialog
        open={confirmDelete}
        onOpenChange={(o) => {
          setConfirmDelete(o);
          if (!o) {
            setDeletePwd("");
            setDeleteWord("");
          }
        }}
      >
        <DialogContent
          className="max-w-md"
          onCloseAutoFocus={onDeleteCloseAutoFocus}
        >
          <DialogHeader>
            <DialogTitle className="text-destructive">
              {t("profile.delete.button")}
            </DialogTitle>
            <DialogDescription>
              {t("profile.section.deleteDesc")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              type="password"
              placeholder={t("profile.delete.confirmPlaceholder")}
              value={deletePwd}
              onChange={(e) => setDeletePwd(e.target.value)}
              autoComplete="current-password"
              aria-label={t("profile.delete.confirmPlaceholder")}
            />
            <div className="space-y-1.5">
              <label htmlFor="delete-confirm-word" className="font-body text-sm font-medium">
                {t("profile.delete.typeLabel", { word: t("profile.delete.typeWord") })}
              </label>
              <Input
                id="delete-confirm-word"
                value={deleteWord}
                onChange={(e) => setDeleteWord(e.target.value)}
                placeholder={t("profile.delete.typePlaceholder")}
                aria-label={t("profile.delete.typeLabel", {
                  word: t("profile.delete.typeWord"),
                })}
                autoComplete="off"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => {
                setConfirmDelete(false);
                setDeletePwd("");
                setDeleteWord("");
              }}
            >
              {t("common.cancel")}
            </Button>
            <Button
              variant="destructive"
              onClick={deleteAccount}
              disabled={
                !deletePwd || deleteWord !== t("profile.delete.typeWord") || deleting
              }
            >
              {t("profile.delete.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/**
 * QA-iter2 — privacy-curious users can download their profile +
 * activity counts as a JSON blob. The backend (`/api/v1/users/me/
 * export`) already returned this payload but no UI surfaced it; the
 * orphan was caught by the FE/BE parity audit. Future enhancement on
 * the backend side will enqueue a Celery job that produces a full
 * zip including chat history + reviews + enrollments — the button
 * here will switch to a "request export" affordance at that point.
 */
function ExportDataCard() {
  const t = useT();
  const [busy, setBusy] = useState(false);

  async function onExport() {
    setBusy(true);
    try {
      const payload = await api<Record<string, unknown>>(
        "/api/v1/users/me/export",
      );
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      // Stable filename + ISO date so users get a chronological history
      // if they export more than once.
      a.download = `lumen-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(t("profile.export.toast"));
    } catch (e) {
      const msg = e instanceof Error ? e.message : t("profile.export.error");
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="mb-5">
        <h2 className="font-display text-lg leading-tight tracking-tight">
          {t("profile.export.title")}
        </h2>
        <p className="mt-1 font-body text-sm text-muted-foreground">
          {t("profile.export.description")}
        </p>
      </div>
      <Button variant="outline" onClick={onExport} disabled={busy}>
        <Download className="me-2 h-4 w-4" aria-hidden />
        {busy ? t("profile.export.busy") : t("profile.export.button")}
      </Button>
    </div>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-10 border-t border-border pt-8">
      <div className="mb-5">
        <h2 className="font-display text-lg leading-tight tracking-tight">{title}</h2>
        <p className="mt-1 font-body text-sm text-muted-foreground">{description}</p>
      </div>
      {children}
    </section>
  );
}
