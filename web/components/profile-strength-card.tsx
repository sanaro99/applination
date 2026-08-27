"use client";

/**
 * The profile meter, permanently.
 *
 * A wizard's progress bar disappears when the wizard does; this is a profile,
 * so it stays. During formation it shows the nine parts and names the single
 * most useful next thing. Once they are all filled the meter has nothing left
 * to say, so it collapses to one line and the card turns into story coverage —
 * a full meter sitting next to a request for more work reads as broken.
 *
 * Coverage is not decoration: `reference_loader._score` weights a tag overlap
 * at +2 (or +5 when it matches a detected role category) against +0.25 for a
 * body keyword, so a gap here is a measurable weakness in the letter the user
 * is about to receive.
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { ProfileMeter } from "@/components/profile-meter";
import { api } from "@/lib/api";

/** Enough to show the shape of the coverage without turning into a tag wall. */
const BADGE_LIMIT = 8;

export function ProfileStrengthCard() {
  const { data } = useQuery({
    queryKey: ["profile-strength"],
    queryFn: () => api.profileStrength(),
    retry: false,
  });

  if (!data) return null;

  const quote = (items: string[]) => items.map((t) => `“${t}”`).join(", ");
  const shown = data.coverage.covered.slice(0, BADGE_LIMIT);
  const rest = data.coverage.covered.length - shown.length;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your profile</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {data.phase === "formation" ? (
          <>
            <ProfileMeter
              parts={data.parts}
              filled={data.filled}
              total={data.total}
              interactive
            />
            {data.next ? (
              <div className="space-y-2">
                <p className="font-medium">Next · {data.next.label}</p>
                <p className="text-sm text-muted-foreground">
                  {data.next.hint}
                </p>
                <Link
                  href="/onboarding"
                  className={buttonVariants({ size: "sm" })}
                >
                  Pick up where you left off
                </Link>
              </div>
            ) : null}
          </>
        ) : (
          <>
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Check className="size-4 text-primary" />
              Profile complete · {data.filled} of {data.total}
            </p>

            <div className="space-y-2">
              <p className="text-sm font-medium">Story coverage</p>
              {shown.length ? (
                <>
                  <div className="flex flex-wrap gap-1">
                    {shown.map((tag) => (
                      <Badge key={tag} variant="secondary">
                        {tag}
                      </Badge>
                    ))}
                    {rest > 0 ? (
                      <Badge variant="outline">+{rest} more</Badge>
                    ) : null}
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {data.coverage.covered.length} of {data.coverage.total} tags
                    covered.
                    {data.coverage.gaps.length
                      ? ` Nothing yet for ${quote(data.coverage.gaps)} — roles tagged that way will get a weaker letter.`
                      : ""}
                  </p>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">
                  None of your stories carry a taxonomy tag yet. Matching then
                  rests on words in the story body, which score far lower than a
                  tag — so your letters get less relevant stories.
                </p>
              )}
              <Link
                href="/master-data"
                className={buttonVariants({ size: "sm", variant: "outline" })}
              >
                Add a story
              </Link>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
