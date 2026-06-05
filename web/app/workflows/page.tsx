"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { WorkflowLlmEditor } from "@/components/workflow-llm-editor";
import { ProvidersPanel } from "@/components/providers-panel";

export default function WorkflowsPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Workflow LLM routing</CardTitle>
        </CardHeader>
        <CardContent>
          <WorkflowLlmEditor />
        </CardContent>
      </Card>
      <ProvidersPanel />
    </div>
  );
}
