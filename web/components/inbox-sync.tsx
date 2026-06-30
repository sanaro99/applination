"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, MailCheck, MailWarning } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { api } from "@/lib/api";

/**
 * "Sync inbox" control: scans the configured Gmail/IMAP inbox for recruiter
 * replies and advances application statuses. Shows a setup hint when the inbox
 * is not configured yet.
 */
export function InboxSync() {
  const qc = useQueryClient();
  const { data: status } = useQuery({
    queryKey: ["inbox-status"],
    queryFn: () => api.inboxStatus(),
    staleTime: 60_000,
  });

  const sync = useMutation({
    mutationFn: () => api.inboxSync(),
    onSuccess: (r) => {
      const n = r.updates.length;
      if (n === 0) {
        toast.success(
          `Inbox synced — ${r.scanned} emails scanned, no status changes.`,
        );
      } else {
        toast.success(
          `Inbox synced — ${n} application${n === 1 ? "" : "s"} updated.`,
          {
            description: r.updates
              .slice(0, 4)
              .map(
                (u) => `${u.company}: ${u.old_status} → ${u.new_status}`,
              )
              .join(" · "),
          },
        );
      }
      qc.invalidateQueries({ queryKey: ["applications"] });
      qc.invalidateQueries({ queryKey: ["inbox-status"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  if (status && !status.configured) {
    return (
      <Link
        href="/config"
        className={buttonVariants({ variant: "ghost", size: "sm" })}
        title="Connect Gmail in config to enable inbox sync"
      >
        <MailWarning className="size-4" />
        Connect inbox
      </Link>
    );
  }

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => sync.mutate()}
      disabled={sync.isPending}
      title={
        status?.last_sync
          ? `Last synced ${new Date(status.last_sync + "Z").toLocaleString()}`
          : "Scan your inbox for recruiter replies"
      }
    >
      {sync.isPending ? (
        <Loader2 className="size-4 animate-spin" />
      ) : (
        <MailCheck className="size-4" />
      )}
      Sync inbox
    </Button>
  );
}
