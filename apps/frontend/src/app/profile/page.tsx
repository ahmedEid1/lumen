"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { ImageUpload } from "@/components/shared/image-upload";
import { SessionsCard } from "@/components/shared/sessions-card";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

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

  const inputClass =
    "border-gold/25 bg-background/60 focus-visible:border-gold/60";

  return (
    <div className="container mx-auto max-w-3xl space-y-8 px-4 py-14">
      <header className="flex flex-col gap-3">
        <Cartouche>{t("profile.cartouche")}</Cartouche>
        <div className="flex items-center gap-5">
          <Avatar className="h-20 w-20 border-2 border-gold/30">
            <AvatarImage src={user.avatar_url ?? undefined} alt={user.full_name} />
            <AvatarFallback className="bg-card text-2xl font-medium text-gold">
              {user.full_name.slice(0, 1).toUpperCase() || "U"}
            </AvatarFallback>
          </Avatar>
          <div className="flex flex-col gap-1.5">
            <h1 className="font-display text-3xl font-medium tracking-tight">
              {user.full_name || user.email}
            </h1>
            <div className="flex flex-wrap items-center gap-2 font-body text-sm text-muted-foreground">
              <span>{user.email}</span>
              <Badge variant="muted" className="capitalize">
                {user.role}
              </Badge>
              {user.email_verified_at ? (
                <Badge className="border border-gold/40 bg-gold/10 text-gold">
                  {t("profile.badge.verified")}
                </Badge>
              ) : (
                <Badge variant="outline" className="border-destructive/50 text-destructive">
                  {t("profile.badge.unverified")}
                </Badge>
              )}
            </div>
          </div>
        </div>
      </header>

      {!user.email_verified_at && (
        <div className="flex flex-col items-start justify-between gap-3 rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm sm:flex-row sm:items-center">
          <p className="flex items-center gap-2 font-body text-destructive-foreground">
            <Glyph name="feather" size={18} mode="tint" className="text-destructive" />
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

      <Card className="scroll-paper border-gold/20">
        <CardHeader>
          <CardTitle className="font-display text-2xl">{t("profile.section.profile")}</CardTitle>
          <CardDescription className="font-body">
            {t("profile.section.profileDesc")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={saveProfile}>
            <div className="space-y-1.5">
              <label htmlFor="full_name" className="font-body text-sm font-medium">
                {t("auth.register.fullName")}
              </label>
              <Input
                id="full_name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className={inputClass}
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
                className={inputClass}
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
        </CardContent>
      </Card>

      <Card className="scroll-paper border-gold/20">
        <CardHeader>
          <CardTitle className="font-display text-2xl">{t("profile.section.password")}</CardTitle>
          <CardDescription className="font-body">
            {t("profile.section.passwordDesc")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={changePassword}>
            <Input
              type="password"
              placeholder={t("profile.field.currentPassword")}
              value={currentPwd}
              onChange={(e) => setCurrentPwd(e.target.value)}
              autoComplete="current-password"
              required
              className={inputClass}
            />
            <Input
              type="password"
              placeholder={t("profile.field.newPasswordPlaceholder")}
              value={newPwd}
              onChange={(e) => setNewPwd(e.target.value)}
              autoComplete="new-password"
              minLength={12}
              required
              className={inputClass}
            />
            <Button type="submit" disabled={savingPwd}>
              {savingPwd ? t("profile.password.submitting") : t("profile.password.submit")}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className="scroll-paper border-gold/20">
        <CardHeader>
          <CardTitle className="font-display text-2xl">{t("profile.section.email")}</CardTitle>
          <CardDescription className="font-body">
            {t("profile.section.emailDesc")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={requestEmailChange}>
            <div className="space-y-1.5">
              <label className="font-body text-sm font-medium">
                {t("profile.field.currentEmail")}
              </label>
              <Input value={user.email} disabled className={inputClass} />
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
                className={inputClass}
              />
            </div>
            <Input
              type="password"
              placeholder={t("profile.field.currentPassword")}
              value={emailPwd}
              onChange={(e) => setEmailPwd(e.target.value)}
              autoComplete="current-password"
              required
              className={inputClass}
            />
            <Button type="submit" disabled={requestingEmail || !newEmail || !emailPwd}>
              {requestingEmail ? t("profile.email.submitting") : t("profile.email.submit")}
            </Button>
          </form>
        </CardContent>
      </Card>

      <SessionsCard />

      <Card className="scroll-paper border-destructive/40">
        <CardHeader>
          <CardTitle className="font-display text-2xl text-destructive">
            {t("profile.section.delete")}
          </CardTitle>
          <CardDescription className="font-body">
            {t("profile.section.deleteDesc")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!confirmDelete ? (
            <Button variant="destructive" onClick={() => setConfirmDelete(true)}>
              {t("profile.delete.button")}
            </Button>
          ) : (
            <div className="space-y-3">
              <Input
                type="password"
                placeholder={t("profile.delete.confirmPlaceholder")}
                value={deletePwd}
                onChange={(e) => setDeletePwd(e.target.value)}
                className={inputClass}
              />
              <div className="flex gap-2">
                <Button variant="destructive" onClick={deleteAccount} disabled={!deletePwd}>
                  {t("profile.delete.confirm")}
                </Button>
                <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
                  {t("common.cancel")}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
