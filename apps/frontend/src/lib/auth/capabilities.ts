"use client";

import { useMemo } from "react";
import { useAuth } from "@/lib/auth/store";
import type { Role, UserOut } from "@/lib/api/types";

/**
 * Client-side mirror of the backend capability model (ADR-0025 / S1.11).
 *
 * The two-role collapse means there is no "instructor" gate anymore: every
 * authenticated, active user may author + clone + publish-public. Admin is the
 * only elevated role. These predicates answer "is the door open at all" — the
 * server still enforces ownership/quota/moderation on every mutation, so this
 * is purely for hiding controls the user can't use, never for security.
 *
 * No server round-trip: capabilities are derived from the loaded `/me` user.
 * A stale `/me` carrying a legacy role is harmless — `canAuthor` keys off
 * presence + active, and `isAdmin` is an exact `=== "admin"` check that a
 * legacy `student`/`instructor` claim can never satisfy.
 */

export interface Capabilities {
  /** Exactly the admin role. */
  isAdmin: boolean;
  /** Any authenticated, active user may author. */
  canAuthor: boolean;
  /** Any authenticated, active user may publish publicly (moderation server-side). */
  canPublishPublic: boolean;
  /** Any authenticated, active user may clone a publicly-listed course. */
  canClone: boolean;
}

function isAdminRole(role: Role | string | undefined): boolean {
  return role === "admin";
}

export function capabilitiesFor(user: UserOut | null): Capabilities {
  const active = !!user && user.is_active !== false;
  return {
    isAdmin: active && isAdminRole(user?.role),
    canAuthor: active,
    canPublishPublic: active,
    canClone: active,
  };
}

export function useCapabilities(): Capabilities {
  const { user } = useAuth();
  return useMemo(() => capabilitiesFor(user), [user]);
}
