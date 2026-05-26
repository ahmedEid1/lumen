"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { AlertTriangle } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { ImageUpload } from "@/components/shared/image-upload";
import { SessionsCard } from "@/components/shared/sessions-card";
import { api } from "@/lib/api/client";
import {
  Me,
  type NotificationDispatch,
  type NotificationKind,
} from "@/lib/api/endpoints";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

const NOTIFICATION_KINDS: NotificationKind[] = [
  "enrolled",
  "lesson_available",
  "certificate_ready",
  "review_received",
  "chat_mention",
  "security",
  "discussion_reply",
];

const DISPATCH_OPTIONS: NotificationDispatch[] = [
  "off",
  "in_app",
  "email_immediate",
  "digest_daily",
];

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
    try {
      await api("/api/v1/users/me", { method: "DELETE", body: { password: deletePwd } });
      toast.success(t("profile.toast.deleted"));
      await logout();
      router.push("/");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("profile.toast.deleteError"));
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
                {NOTIFICATION_KINDS.map((kind) => (
                  <div
                    key={kind}
                    className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <label
                      htmlFor={`pref-${kind}`}
                      className="font-body text-sm font-medium"
                    >
                      {t(`prefs.notifications.kind.${kind}`)}
                    </label>
                    <select
                      id={`pref-${kind}`}
                      value={notifPrefs[kind] ?? "in_app"}
                      onChange={(e) =>
                        setNotifPrefs((prev) =>
                          prev
                            ? {
                                ...prev,
                                [kind]: e.target.value as NotificationDispatch,
                              }
                            : prev,
                        )
                      }
                      className="h-9 rounded-md border border-border bg-background px-3 text-sm transition-colors duration-[160ms] focus:border-foreground focus:outline-none"
                    >
                      {DISPATCH_OPTIONS.map((opt) => (
                        <option key={opt} value={opt}>
                          {t(`prefs.notifications.dispatch.${opt}`)}
                        </option>
                      ))}
                    </select>
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
          if (!o) setDeletePwd("");
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="text-destructive">
              {t("profile.delete.button")}
            </DialogTitle>
            <DialogDescription>
              {t("profile.section.deleteDesc")}
            </DialogDescription>
          </DialogHeader>
          <Input
            type="password"
            placeholder={t("profile.delete.confirmPlaceholder")}
            value={deletePwd}
            onChange={(e) => setDeletePwd(e.target.value)}
            aria-label={t("profile.delete.confirmPlaceholder")}
          />
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => {
                setConfirmDelete(false);
                setDeletePwd("");
              }}
            >
              {t("common.cancel")}
            </Button>
            <Button
              variant="destructive"
              onClick={deleteAccount}
              disabled={!deletePwd}
            >
              {t("profile.delete.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
