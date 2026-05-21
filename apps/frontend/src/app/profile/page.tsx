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
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";

export default function ProfilePage() {
  const { user, ready, refresh, logout } = useAuth();
  const router = useRouter();
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
      toast.success("Profile updated");
      await refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save");
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
      toast.success("Password changed. Sign in again to refresh sessions.");
      setCurrentPwd("");
      setNewPwd("");
      await logout();
      router.push("/login");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not change password");
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
      toast.success(`We sent a confirmation link to ${newEmail}. Click it within an hour.`);
      setNewEmail("");
      setEmailPwd("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not start email change");
    } finally {
      setRequestingEmail(false);
    }
  }

  async function deleteAccount() {
    try {
      await api("/api/v1/users/me", { method: "DELETE", body: { password: deletePwd } });
      toast.success("Account deleted");
      await logout();
      router.push("/");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not delete account");
    }
  }

  return (
    <div className="container mx-auto max-w-3xl space-y-6 px-4 py-10">
      <header className="flex items-center gap-4">
        <Avatar className="h-16 w-16">
          <AvatarImage src={user.avatar_url ?? undefined} alt={user.full_name} />
          <AvatarFallback>{user.full_name.slice(0, 1).toUpperCase() || "U"}</AvatarFallback>
        </Avatar>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{user.full_name || user.email}</h1>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span>{user.email}</span>
            <Badge variant="muted" className="capitalize">
              {user.role}
            </Badge>
            {user.email_verified_at ? (
              <Badge variant="secondary">verified</Badge>
            ) : (
              <Badge variant="outline">unverified</Badge>
            )}
          </div>
        </div>
      </header>

      {!user.email_verified_at && (
        <div className="flex items-center justify-between rounded-lg border border-amber-500/40 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          <p>Your email isn&apos;t verified yet — check your inbox or resend the link.</p>
          <Button
            size="sm"
            variant="outline"
            onClick={async () => {
              try {
                await api("/api/v1/auth/verify/request", { method: "POST" });
                toast.success("Verification email sent");
              } catch (e) {
                toast.error(e instanceof Error ? e.message : "Could not send verification email");
              }
            }}
          >
            Resend
          </Button>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>How others see you on Lumen.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={saveProfile}>
            <div className="space-y-1.5">
              <label htmlFor="full_name" className="text-sm font-medium">
                Full name
              </label>
              <Input id="full_name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="bio" className="text-sm font-medium">
                Bio
              </label>
              <Textarea id="bio" rows={4} value={bio} onChange={(e) => setBio(e.target.value)} />
            </div>
            <ImageUpload
              kind="avatar"
              shape="circle"
              label="Avatar"
              value={avatarUrl || null}
              onChange={(u) => setAvatarUrl(u ?? "")}
            />
            <Button type="submit" disabled={savingProfile}>
              {savingProfile ? "Saving…" : "Save changes"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Change password</CardTitle>
          <CardDescription>You&apos;ll be signed out of other sessions.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={changePassword}>
            <Input
              type="password"
              placeholder="Current password"
              value={currentPwd}
              onChange={(e) => setCurrentPwd(e.target.value)}
              autoComplete="current-password"
              required
            />
            <Input
              type="password"
              placeholder="New password (≥ 12 chars)"
              value={newPwd}
              onChange={(e) => setNewPwd(e.target.value)}
              autoComplete="new-password"
              minLength={12}
              required
            />
            <Button type="submit" disabled={savingPwd}>
              {savingPwd ? "Updating…" : "Update password"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Change email</CardTitle>
          <CardDescription>
            We&apos;ll send a confirmation link to the new address. The change
            doesn&apos;t take effect until you click it, and all your other
            sessions will be signed out for security.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={requestEmailChange}>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Current email</label>
              <Input value={user.email} disabled />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="new_email" className="text-sm font-medium">
                New email
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
              placeholder="Current password"
              value={emailPwd}
              onChange={(e) => setEmailPwd(e.target.value)}
              autoComplete="current-password"
              required
            />
            <Button type="submit" disabled={requestingEmail || !newEmail || !emailPwd}>
              {requestingEmail ? "Sending…" : "Send confirmation link"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <SessionsCard />

      <Card>
        <CardHeader>
          <CardTitle className="text-destructive">Delete account</CardTitle>
          <CardDescription>This permanently deactivates your account.</CardDescription>
        </CardHeader>
        <CardContent>
          {!confirmDelete ? (
            <Button variant="destructive" onClick={() => setConfirmDelete(true)}>
              Delete my account
            </Button>
          ) : (
            <div className="space-y-3">
              <Input
                type="password"
                placeholder="Confirm with your password"
                value={deletePwd}
                onChange={(e) => setDeletePwd(e.target.value)}
              />
              <div className="flex gap-2">
                <Button variant="destructive" onClick={deleteAccount} disabled={!deletePwd}>
                  Yes, delete my account
                </Button>
                <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
