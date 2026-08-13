"use client";

import { Suspense } from "react";

import { AuthForm } from "@/components/auth-form";

export default function LoginPage() {
  // useSearchParams (for ?next=) needs a Suspense boundary.
  return (
    <Suspense>
      <AuthForm mode="login" />
    </Suspense>
  );
}
