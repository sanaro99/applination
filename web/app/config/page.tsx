"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TextEditor } from "@/components/text-editor";
import { ProvidersPanel } from "@/components/providers-panel";
import { GmailConnectCard } from "@/components/gmail-connect-card";
import { StoredSecretsCard } from "@/components/stored-secrets-card";
import { ConfigForm } from "@/components/config/config-form";
import { api } from "@/lib/api";

export default function ConfigPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div id="tour-providers">
        <ProvidersPanel />
      </div>
      <StoredSecretsCard />
      <GmailConnectCard />
      <Card>
        <CardHeader>
          <CardTitle>Settings</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="form">
            <TabsList>
              <TabsTrigger value="form">Form</TabsTrigger>
              <TabsTrigger value="raw">Advanced: YAML</TabsTrigger>
            </TabsList>
            <TabsContent value="form" className="mt-4">
              <ConfigForm />
            </TabsContent>
            <TabsContent value="raw" className="mt-4">
              <RawConfigEditor />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}

function RawConfigEditor() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["config"],
    queryFn: () => api.getConfig(),
  });
  if (isLoading || !data) return <Skeleton className="h-[60svh] w-full" />;
  return (
    <div className="space-y-3">
      <TextEditor
        initial={data.text}
        language="yaml"
        onSave={async (text) => {
          await api.putConfig(text);
          // All three: saving may have moved an API key out of the file into
          // encrypted storage, which changes the config text *and* the
          // stored-keys list, and it can change anything the form renders.
          await qc.invalidateQueries({ queryKey: ["config"] });
          await qc.invalidateQueries({ queryKey: ["config-structured"] });
          await qc.invalidateQueries({ queryKey: ["secrets"] });
        }}
      />
      <p className="text-xs text-muted-foreground">
        The whole file, including the sections the form leaves alone: your LLM
        routing, Gmail client, contact details and pricing windows. Saves are
        validated as YAML before being written.
      </p>
    </div>
  );
}
