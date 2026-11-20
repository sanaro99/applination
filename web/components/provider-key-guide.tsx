"use client";

import { AlertTriangle, BookOpen, CreditCard, ExternalLink, KeyRound, UserPlus } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import type { ProviderSetup } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * How to get a key for one provider: the steps, the links, and what a valid key
 * looks like.
 *
 * Shared by the onboarding journey and the Config page's Configure dialog so the
 * two never drift. The copy is data from `server/provider_setup.py`; this
 * component only lays it out. The key-page link is the primary action because
 * it survives a vendor redesign better than any of the steps around it.
 */
export function ProviderKeyGuide({
  provider,
  className,
}: {
  provider: ProviderSetup;
  className?: string;
}) {
  const secondary = [
    provider.signup_url && { href: provider.signup_url, label: "Sign up", icon: UserPlus },
    provider.billing_url && { href: provider.billing_url, label: "Add credit", icon: CreditCard },
    provider.docs_url && { href: provider.docs_url, label: "Official docs", icon: BookOpen },
  ].filter(Boolean) as { href: string; label: string; icon: typeof UserPlus }[];

  return (
    <div className={cn("space-y-3", className)}>
      <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
        {provider.steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>

      <div className="flex flex-wrap items-center gap-2">
        <a
          href={provider.console_url}
          target="_blank"
          rel="noopener noreferrer"
          className={buttonVariants({ size: "sm" })}
        >
          {provider.needs_key ? "Open key page" : `Open ${provider.label}`}
          <ExternalLink className="size-3.5" />
        </a>
        {secondary.map(({ href, label, icon: Icon }) => (
          <a
            key={label}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className={buttonVariants({ size: "sm", variant: "outline" })}
          >
            <Icon className="size-3.5" /> {label}
          </a>
        ))}
      </div>

      {provider.needs_key && provider.key_hint ? (
        <p className="flex items-start gap-2 text-xs text-muted-foreground">
          <KeyRound className="mt-0.5 size-3.5 shrink-0 text-primary" />
          <span>
            <span className="font-medium text-foreground">What it looks like: </span>
            {provider.key_hint}
          </span>
        </p>
      ) : null}

      {provider.shown_once ? (
        <p className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          {provider.label} shows the full key only once. Copy it before closing the
          page; if you lose it, create a new one.
        </p>
      ) : null}

      <p className="text-xs text-muted-foreground">{provider.cost_note}</p>

      {provider.stale ? (
        <p className="text-xs text-muted-foreground">
          These steps were checked on {provider.verified_on} and may have moved.
          The key-page link is the thing to trust.
        </p>
      ) : null}
    </div>
  );
}
