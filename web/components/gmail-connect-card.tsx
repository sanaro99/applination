"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, Copy, Loader2, Mail } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";

/**
 * Gmail OAuth connect/disconnect card for the Config page. Client id/secret
 * come from a Google Cloud Console OAuth client the user already created;
 * "Connect with Google" opens the backend's /oauth/authorize redirect in a
 * popup, which lands on Google's consent screen and back on our callback.
 */
export function GmailConnectCard() {
  const qc = useQueryClient();
  const { data: status, isLoading } = useQuery({
    queryKey: ["inbox-status"],
    queryFn: () => api.inboxStatus(),
  });

  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");

  useEffect(() => {
    function onMessage(e: MessageEvent) {
      if (e.data === "gmail-connected") {
        toast.success("Gmail connected.");
        qc.invalidateQueries({ queryKey: ["inbox-status"] });
        qc.invalidateQueries({ queryKey: ["reminders-status"] });
      } else if (e.data === "gmail-error") {
        toast.error("Gmail sign-in failed. Check the popup window for details.");
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [qc]);

  const saveCreds = useMutation({
    mutationFn: () => api.inboxOauthCredentials(clientId, clientSecret),
    onSuccess: () => {
      toast.success("OAuth client saved.");
      qc.invalidateQueries({ queryKey: ["inbox-status"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  const disconnect = useMutation({
    mutationFn: () => api.inboxOauthDisconnect(),
    onSuccess: () => {
      toast.success("Gmail disconnected.");
      qc.invalidateQueries({ queryKey: ["inbox-status"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  function connect() {
    window.open(api.inboxOauthAuthorizeUrl(), "gmail-oauth", "width=480,height=640");
  }

  function copyRedirect() {
    if (status?.redirect_uri) {
      navigator.clipboard.writeText(status.redirect_uri);
      toast.success("Redirect URI copied.");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Mail className="size-4 text-primary" /> Connect Gmail
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading || !status ? (
          <Skeleton className="h-32 w-full" />
        ) : (
          <>
            {status.configured ? (
              <div className="flex flex-wrap items-center gap-3 rounded-md border border-border/60 p-3">
                <CheckCircle2 className="size-4 text-emerald-600 dark:text-emerald-400" />
                <span className="text-sm">
                  Connected as <span className="font-medium">{status.account_email}</span>
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  className="ml-auto"
                  onClick={() => disconnect.mutate()}
                  disabled={disconnect.isPending}
                >
                  {disconnect.isPending && <Loader2 className="size-3.5 animate-spin" />}
                  Disconnect
                </Button>
              </div>
            ) : (
              <>
                <p className="text-sm text-muted-foreground">
                  Paste the OAuth client from your Google Cloud Console project (with the
                  Gmail API enabled), add the redirect URI below to that client&apos;s
                  Authorized redirect URIs, then connect.
                </p>
                <div className="space-y-2">
                  <Label htmlFor="gmail-client-id">Client ID</Label>
                  <Input
                    id="gmail-client-id"
                    value={clientId}
                    onChange={(e) => setClientId(e.target.value)}
                    placeholder="xxxxx.apps.googleusercontent.com"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="gmail-client-secret">Client secret</Label>
                  <Input
                    id="gmail-client-secret"
                    type="password"
                    value={clientSecret}
                    onChange={(e) => setClientSecret(e.target.value)}
                    placeholder="GOCSPX-..."
                  />
                </div>
                <div className="space-y-2">
                  <Label>Redirect URI (add to your OAuth client)</Label>
                  <div className="flex items-center gap-2">
                    <Input readOnly value={status.redirect_uri} className="font-mono text-xs" />
                    <Button size="sm" variant="outline" onClick={copyRedirect}>
                      <Copy className="size-3.5" />
                    </Button>
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => saveCreds.mutate()}
                    disabled={saveCreds.isPending || !clientId || !clientSecret}
                  >
                    {saveCreds.isPending && <Loader2 className="size-3.5 animate-spin" />}
                    Save client
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={connect}
                    disabled={!status.has_client_credentials}
                    title={
                      status.has_client_credentials
                        ? undefined
                        : "Save the client ID/secret first"
                    }
                  >
                    Connect with Google
                  </Button>
                </div>
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
