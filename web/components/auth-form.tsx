"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api";

/** Mirrors auth.MIN_PASSWORD_LENGTH — the server rejects anything shorter. */
const MIN_PASSWORD_LENGTH = 12;

type Mode = "login" | "signup";

const COPY = {
  login: {
    title: "Sign in",
    submit: "Sign in",
    switchPrompt: "Need an account?",
    switchLabel: "Create one",
    switchHref: "/signup",
  },
  signup: {
    title: "Create your account",
    submit: "Create account",
    switchPrompt: "Already have an account?",
    switchLabel: "Sign in",
    switchHref: "/login",
  },
} as const;

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const copy = COPY[mode];

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const tooShort = mode === "signup" && password.length > 0 &&
    password.length < MIN_PASSWORD_LENGTH;

  // Only offered when the server says a demo exists. A private deployment sets
  // DEMO_ENABLED=0 and the link disappears rather than 404ing on click.
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    staleTime: 5 * 60 * 1000,
  });

  async function onDemo() {
    setError(null);
    setBusy(true);
    try {
      const user = await api.demoLogin();
      queryClient.setQueryData(["me"], user);
      await queryClient.invalidateQueries();
      router.replace("/");
    } catch {
      setError("The demo is unavailable right now.");
      setBusy(false);
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user =
        mode === "login"
          ? await api.login(email, password)
          : await api.signup(email, password);
      // Seed the cache so AuthGate does not bounce back to /login on the way in.
      queryClient.setQueryData(["me"], user);
      // Any previous account's data must not survive the switch.
      await queryClient.invalidateQueries();
      const next = params.get("next");
      router.replace(next && next.startsWith("/") ? next : "/");
    } catch (err) {
      setError(messageFor(err, mode));
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>{copy.title}</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {mode === "signup" && (
                <p
                  className={
                    tooShort
                      ? "text-xs text-destructive"
                      : "text-xs text-muted-foreground"
                  }
                >
                  At least {MIN_PASSWORD_LENGTH} characters.
                </p>
              )}
            </div>

            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}

            <Button
              type="submit"
              className="w-full"
              disabled={busy || tooShort || !email || !password}
            >
              {busy && <Loader2 className="mr-2 size-4 animate-spin" />}
              {copy.submit}
            </Button>
          </form>

          <p className="mt-4 text-center text-sm text-muted-foreground">
            {copy.switchPrompt}{" "}
            <Link href={copy.switchHref} className="underline">
              {copy.switchLabel}
            </Link>
          </p>
        </CardContent>
      </Card>

      {/* Deliberately a muted line beside the card rather than a button: it
          must not compete with the primary call to action. */}
      {health?.demo && (
        <p className="mt-3 w-full max-w-sm text-right text-xs text-muted-foreground">
          Just exploring?{" "}
          <button
            type="button"
            onClick={onDemo}
            disabled={busy}
            className="underline underline-offset-2 hover:text-foreground disabled:opacity-50"
          >
            Try the demo
          </button>
        </p>
      )}
    </div>
  );
}

function messageFor(err: unknown, mode: Mode): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "Invalid email or password.";
    // The API answers a duplicate signup vaguely on purpose, so it is not an
    // account-enumeration oracle. Say the same thing here.
    if (err.status === 409) return "Could not create that account.";
    if (err.status === 422) {
      return mode === "signup"
        ? `Check the email format, and use at least ${MIN_PASSWORD_LENGTH} characters.`
        : "Check the email and password.";
    }
    if (err.status === 429) {
      return "Too many attempts. Wait a minute and try again.";
    }
  }
  return "Something went wrong. Try again.";
}
