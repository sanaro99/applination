"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Sparkles, Download } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { api, downloadUrl } from "@/lib/api";
import { ResumeDiff } from "@/components/resume-diff";

export function TweakPanel({
  appId,
  folderRel,
}: {
  appId: number;
  folderRel: string;
}) {
  const qc = useQueryClient();
  const [instruction, setInstruction] = useState("");
  const { data: versions } = useQuery({
    queryKey: ["resume-versions", appId],
    queryFn: () => api.listResumeVersions(appId),
  });
  const tweak = useMutation({
    mutationFn: () => api.tweakResume(appId, instruction.trim()),
    onSuccess: (r) => {
      toast.success(`Created ${r.docx_filename}`);
      setInstruction("");
      qc.invalidateQueries({ queryKey: ["resume-versions", appId] });
    },
    onError: (e) => toast.error(String(e)),
  });
  const list = versions?.versions ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="size-4 text-primary" /> Tweak resume
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder='e.g. "Emphasize LangGraph and RAG experience over web dev."'
          className="min-h-28"
        />
        <Button
          onClick={() => tweak.mutate()}
          disabled={!instruction.trim() || tweak.isPending}
        >
          {tweak.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Sparkles className="size-4" />
          )}
          Generate version
        </Button>
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Versions
          </p>
          <div className="flex flex-wrap gap-2">
            {list.map((v) => (
              <div
                key={v.docx}
                className="flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-xs"
              >
                <Badge variant="outline" className="font-mono">
                  {v.version > 1 ? `v${v.version}` : "original"}
                </Badge>
                {v.pdf && (
                  <a
                    href={downloadUrl(appId, "resume", "pdf", v.version)}
                    className={buttonVariants({ variant: "ghost", size: "xs" })}
                    download
                    aria-label={`Download v${v.version} PDF`}
                  >
                    <Download className="size-3" /> PDF
                  </a>
                )}
                <a
                  href={downloadUrl(appId, "resume", "docx", v.version)}
                  className={buttonVariants({ variant: "ghost", size: "xs" })}
                  download
                  aria-label={`Download v${v.version} DOCX`}
                >
                  <Download className="size-3" /> DOCX
                </a>
              </div>
            ))}
            {list.length === 0 && (
              <p className="text-xs text-muted-foreground">
                No versions yet.
              </p>
            )}
          </div>
        </div>

        {list.filter((v) => v.json).length >= 2 && (
          <>
            <Separator />
            <div className="space-y-2">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                Compare versions
              </p>
              <ResumeDiff folderRel={folderRel} versions={list} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
