"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarArrowDown, Copy, Loader2, Mail, RefreshCw, Send } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, API_BASE } from "@/lib/api";

/**
 * Reminders: subscribe/download the live .ics calendar (deadlines + interviews)
 * and email yourself the daily digest. Sending reuses the inbox Gmail
 * credentials, so it's gated on those being configured.
 *
 * The calendar URL carries a signed per-user token rather than relying on the
 * session cookie, because the calendar app fetching it is not the browser and
 * sends no cookies. That makes the link itself the credential — hence the
 * rotate button, which revokes every previously copied URL.
 */
export function RemindersCard() {
  const qc = useQueryClient();

  const { data: status } = useQuery({
    queryKey: ["reminders-status"],
    queryFn: () => api.remindersStatus(),
    staleTime: 60_000,
  });

  const { data: feed } = useQuery({
    queryKey: ["calendar-feed"],
    queryFn: () => api.calendarFeed(),
    staleTime: Infinity,
  });

  const rotate = useMutation({
    mutationFn: () => api.rotateCalendarFeed(),
    onSuccess: (r) => {
      qc.setQueryData(["calendar-feed"], r);
      toast.success("New calendar link generated. The old one no longer works.");
    },
    onError: (e) => toast.error(String(e)),
  });

  const feedUrl = feed ? `${API_BASE}${feed.path}` : "";
  const absoluteFeedUrl =
    feedUrl && typeof window !== "undefined"
      ? new URL(feedUrl, window.location.origin).toString()
      : feedUrl;

  const send = useMutation({
    mutationFn: () => api.digestSend(),
    onSuccess: (r) => toast.success(`Digest emailed to ${r.to}`),
    onError: (e) => toast.error(String(e)),
  });

  const c = status?.counts;
  const summary = c
    ? `${c.deadlines} deadline${c.deadlines === 1 ? "" : "s"} · ${c.interviews} interview${c.interviews === 1 ? "" : "s"} · ${c.follow_ups} to follow up`
    : "Deadlines, interviews, and follow-up nudges.";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Mail className="size-4 text-primary" />
          Reminders
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">{summary}</p>
        <div className="flex flex-wrap gap-2">
          <a
            href={feedUrl || undefined}
            aria-disabled={!feedUrl}
            target="_blank"
            rel="noreferrer"
            className={buttonVariants({ variant: "outline", size: "sm" })}
            title="Open or import into Google Calendar / Apple Calendar / Outlook"
          >
            <CalendarArrowDown className="size-4" />
            Calendar (.ics)
          </a>
          <Button
            variant="outline"
            size="sm"
            disabled={!absoluteFeedUrl}
            onClick={() => {
              navigator.clipboard.writeText(absoluteFeedUrl);
              toast.success("Subscription URL copied. Paste it into your calendar app.");
            }}
            title="Copy the subscribe-by-URL link for Google/Apple Calendar"
          >
            <Copy className="size-4" />
            Copy link
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={rotate.isPending}
            onClick={() => rotate.mutate()}
            title="Revoke the current link and generate a new one"
          >
            {rotate.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCw className="size-4" />
            )}
            Reset link
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => send.mutate()}
            disabled={send.isPending || !status?.can_send_email}
            title={
              status?.can_send_email
                ? "Email yourself the digest now"
                : "Connect Gmail on the Config page to enable email"
            }
          >
            {send.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Send className="size-4" />
            )}
            Email digest
          </Button>
        </div>
        {!status?.can_send_email && (
          <p className="text-xs text-muted-foreground">
            Email sending needs Gmail connected on the Config page. The calendar
            feed works without it.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
