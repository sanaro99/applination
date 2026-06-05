"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarArrowDown, Loader2, Mail, Send } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";

/**
 * Reminders: subscribe/download the live .ics calendar (deadlines + interviews)
 * and email yourself the daily digest. Sending reuses the inbox Gmail
 * credentials, so it's gated on those being configured.
 */
export function RemindersCard() {
  const { data: status } = useQuery({
    queryKey: ["reminders-status"],
    queryFn: () => api.remindersStatus(),
    staleTime: 60_000,
  });

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
            href={api.calendarUrl()}
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
            onClick={() => send.mutate()}
            disabled={send.isPending || !status?.can_send_email}
            title={
              status?.can_send_email
                ? "Email yourself the digest now"
                : "Add a Gmail App Password in config to enable email"
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
            Email sending needs a Gmail App Password in config. The calendar feed
            works without it.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
