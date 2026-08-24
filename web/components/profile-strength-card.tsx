"use client";

/**
 * The fingerprint, permanently.
 *
 * A wizard's progress bar disappears when the wizard does; this is a profile,
 * so it stays. During formation it names the single most useful next thing.
 * After that it stops showing a percentage entirely and reports story coverage
 * against the committed tag taxonomy — which is not decoration:
 * `reference_loader.match_stories` scores by tag overlap, so a gap here is a
 * measurable weakness in the letter the user is about to receive.
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { buttonVariants } from "@/components/ui/button";
import { Fingerprint } from "@/components/onboarding/fingerprint";
import { api } from "@/lib/api";

export function ProfileStrengthCard() {
  const { data } = useQuery({
    queryKey: ["profile-strength"],
    queryFn: () => api.profileStrength(),
    retry: false,
  });

  if (!data) return null;

  const list = (items: string[]) =>
    items.map((t) => `“${t}”`).join(", ");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your profile</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-6 sm:flex-row sm:items-center">
        <Fingerprint
          ridges={data.ridges}
          filled={data.filled}
          total={data.total}
          size={120}
        />
        <div className="flex-1 space-y-3">
          {data.phase === "formation" && data.next ? (
            <>
              <p className="font-medium">{data.next.label}</p>
              <p className="text-sm text-muted-foreground">{data.next.hint}</p>
              <Link
                href="/onboarding"
                className={buttonVariants({ size: "sm" })}
              >
                Pick up where you left off
              </Link>
            </>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                {data.coverage.covered.length
                  ? `Your stories cover ${list(data.coverage.covered)}.`
                  : "Your stories aren't tagged with anything in the taxonomy yet."}
                {data.coverage.gaps.length
                  ? ` Nothing yet for ${list(data.coverage.gaps)} — roles tagged that way will get a weaker letter.`
                  : ""}
              </p>
              <Link
                href="/master-data"
                className={buttonVariants({ size: "sm", variant: "outline" })}
              >
                Add a story
              </Link>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
