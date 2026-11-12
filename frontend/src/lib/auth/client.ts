"use client";

import { createAuthClient } from '@neondatabase/auth';
import { BetterAuthReactAdapter } from '@neondatabase/auth/react/adapters';

const authUrl =
  process.env.NEXT_PUBLIC_NEON_AUTH_URL ||
  (typeof window !== "undefined"
    ? `${window.location.origin}/api/auth`
    : "http://localhost:3000/api/auth");

export const authClient = createAuthClient(authUrl, {
  adapter: BetterAuthReactAdapter(),
});

