"use client";

import { useQuery } from "@tanstack/react-query";
import { KeyRound, ShieldAlert, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";

/**
 * Which API keys are stored, masked.
 *
 * This card exists because saving a key now *removes* it from config.yaml: the
 * value is encrypted into the database and the YAML field is written back
 * empty. Without something showing "a key is stored", the editor below would
 * look like the key had simply been lost, and the natural response would be to
 * paste it again on every visit.
 */
export function StoredSecretsCard() {
  const { data } = useQuery({
    queryKey: ["secrets"],
    queryFn: () => api.getSecrets(),
  });

  if (!data) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="size-4 text-primary" />
          Stored keys
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {!data.key_configured ? (
          <p className="flex items-start gap-2 text-sm text-muted-foreground">
            <ShieldAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
            {data.detail ??
              "The server has no encryption key configured, so API keys cannot be stored."}
          </p>
        ) : data.secrets.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No keys stored yet. Add one under <code>llm.&lt;provider&gt;.api_key</code>{" "}
            in the editor below and save — it will be encrypted and the field
            cleared.
          </p>
        ) : (
          <>
            <ul className="space-y-1.5">
              {data.secrets.map((s) => (
                <li
                  key={s.name}
                  className="flex items-center justify-between gap-3 text-sm"
                >
                  <code className="text-muted-foreground">{s.name}</code>
                  {s.readable ? (
                    <Badge variant="secondary" className="font-mono">
                      <ShieldCheck className="mr-1 size-3" />
                      {s.preview}
                    </Badge>
                  ) : (
                    <Badge variant="destructive">unreadable</Badge>
                  )}
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground">
              Stored encrypted, never written back into config.yaml. Paste a new
              value over the empty field to replace one.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
