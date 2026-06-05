"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TextEditor } from "@/components/text-editor";
import { ProvidersPanel } from "@/components/providers-panel";
import { api } from "@/lib/api";

export default function ConfigPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["config"],
    queryFn: () => api.getConfig(),
  });
  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <ProvidersPanel />
      <Card>
        <CardHeader>
          <CardTitle>config.yaml</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading || !data ? (
            <Skeleton className="h-[60svh] w-full" />
          ) : (
            <TextEditor
              initial={data.text}
              language="yaml"
              onSave={async (text) => {
                await api.putConfig(text);
                await qc.invalidateQueries({ queryKey: ["config"] });
              }}
            />
          )}
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">
        Saves are validated as YAML before being written. Editor reloads
        whenever the file changes on disk between sessions.
      </p>
    </div>
  );
}
