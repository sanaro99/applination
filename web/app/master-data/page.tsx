"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Plus, Sparkles, X } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { TextEditor } from "@/components/text-editor";
import { AiAssist } from "@/components/ai-assist";
import { ProviderSelect } from "@/components/provider-select";
import { api } from "@/lib/api";

type Kind = "story" | "bio" | "resume";

export default function MasterDataPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Master data</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="resume">
            <TabsList>
              <TabsTrigger value="resume">resume.yaml</TabsTrigger>
              <TabsTrigger value="bio">bio.md</TabsTrigger>
              <TabsTrigger value="stories">Stories</TabsTrigger>
              <TabsTrigger value="roles">Target roles</TabsTrigger>
            </TabsList>
            <TabsContent value="resume" className="mt-4">
              <ResumeEditor />
            </TabsContent>
            <TabsContent value="bio" className="mt-4">
              <BioEditor />
            </TabsContent>
            <TabsContent value="stories" className="mt-4">
              <StoriesEditor />
            </TabsContent>
            <TabsContent value="roles" className="mt-4">
              <RolesEditor />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Controlled editor + AI-assist panel. Holds the working text so the AI panel
 * can read the current content and replace it; Save/Reset compare to `disk`.
 */
function EditableDoc({
  disk,
  kind,
  language,
  onSave,
  minHeight,
  aiPlaceholder,
}: {
  disk: string;
  kind: Kind;
  language: "yaml" | "markdown";
  onSave: (text: string) => Promise<unknown>;
  minHeight?: string;
  aiPlaceholder?: string;
}) {
  const [value, setValue] = useState(disk);
  const [baseline, setBaseline] = useState(disk);
  return (
    <div className="space-y-3">
      <AiAssist
        placeholder={aiPlaceholder}
        run={(instruction, provider) =>
          api
            .tweakContent({
              kind,
              text: value,
              instruction,
              provider: provider ?? undefined,
            })
            .then((r) => r.text)
        }
        onResult={setValue}
      />
      <TextEditor
        value={value}
        onValueChange={setValue}
        baseline={baseline}
        language={language}
        minHeight={minHeight}
        onSave={async (text) => {
          await onSave(text);
          setBaseline(text);
        }}
      />
    </div>
  );
}

function ResumeEditor() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["resume"],
    queryFn: () => api.getResume(),
  });
  if (isLoading || !data) return <Skeleton className="h-[60svh] w-full" />;
  return (
    <EditableDoc
      key="resume"
      disk={data.text}
      kind="resume"
      language="yaml"
      aiPlaceholder="e.g. add a bullet about the AIMS product competition to UBS"
      onSave={async (text) => {
        await api.putResume(text);
        await qc.invalidateQueries({ queryKey: ["resume"] });
      }}
    />
  );
}

function BioEditor() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["bio"],
    queryFn: () => api.getBio(),
  });
  if (isLoading || !data) return <Skeleton className="h-[60svh] w-full" />;
  return (
    <EditableDoc
      key="bio"
      disk={data.text}
      kind="bio"
      language="markdown"
      aiPlaceholder="e.g. make the tone a little warmer; add a line about teaching"
      onSave={async (text) => {
        await api.putBio(text);
        await qc.invalidateQueries({ queryKey: ["bio"] });
      }}
    />
  );
}

function StoriesEditor() {
  const qc = useQueryClient();
  const { data: stories } = useQuery({
    queryKey: ["stories"],
    queryFn: () => api.listStories(),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [newOpen, setNewOpen] = useState(false);

  const effectiveSelected =
    selected ?? (stories && stories.length > 0 ? stories[0].name : null);

  const { data: story, isLoading } = useQuery({
    queryKey: ["story", effectiveSelected],
    queryFn: () => api.getStory(effectiveSelected!),
    enabled: !!effectiveSelected,
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Select value={effectiveSelected ?? ""} onValueChange={setSelected}>
          <SelectTrigger className="w-72">
            <SelectValue placeholder="Pick a story…" />
          </SelectTrigger>
          <SelectContent>
            {(stories ?? []).map((s) => (
              <SelectItem key={s.name} value={s.name}>
                {s.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="outline" className="gap-2" onClick={() => setNewOpen(true)}>
          <Plus className="size-4" /> New story
        </Button>
      </div>

      {!effectiveSelected ? (
        <p className="text-sm text-muted-foreground">
          No stories yet. Click <strong>New story</strong> to draft one from a
          short description.
        </p>
      ) : isLoading || !story ? (
        <Skeleton className="h-[55svh] w-full" />
      ) : (
        <EditableDoc
          key={effectiveSelected}
          disk={story.text}
          kind="story"
          language="markdown"
          minHeight="min-h-[55svh]"
          aiPlaceholder="e.g. add more technical detail about the LangGraph validation loop"
          onSave={async (text) => {
            await api.putStory(effectiveSelected, text);
            await qc.invalidateQueries({ queryKey: ["story", effectiveSelected] });
          }}
        />
      )}

      <NewStoryDialog
        open={newOpen}
        onOpenChange={setNewOpen}
        onSaved={(name) => {
          qc.invalidateQueries({ queryKey: ["stories"] });
          setSelected(name);
        }}
      />
    </div>
  );
}

function RolesEditor() {
  const { data, isLoading } = useQuery({
    queryKey: ["search-keywords"],
    queryFn: () => api.getSearchKeywords(),
  });
  if (isLoading || !data) return <Skeleton className="h-[40svh] w-full" />;
  return <RolesEditorInner key={data.keywords.join("\n")} initial={data.keywords} />;
}

function RolesEditorInner({ initial }: { initial: string[] }) {
  const qc = useQueryClient();
  const [list, setKeywords] = useState<string[]>(initial);
  const [baseline] = useState<string[]>(initial);

  const [manual, setManual] = useState("");
  const [description, setDescription] = useState("");
  const [provider, setProvider] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const suggest = useMutation({
    mutationFn: () =>
      api.suggestKeywords({
        description: description.trim(),
        existing: list,
        provider: provider ?? undefined,
      }),
    onSuccess: (r) => {
      const fresh = r.keywords.filter((k) => !list.includes(k));
      if (fresh.length === 0) {
        toast.info("No new suggestions — try describing it differently.");
      }
      setSuggestions(fresh);
    },
    onError: (e) => toast.error(String(e)),
  });

  const save = useMutation({
    mutationFn: (kw: string[]) => api.putSearchKeywords(kw),
    onSuccess: () => {
      toast.success("Target roles saved");
      qc.invalidateQueries({ queryKey: ["search-keywords"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  function addKeyword(k: string) {
    const v = k.trim();
    if (!v || list.includes(v)) return;
    setKeywords([...list, v]);
  }

  function removeKeyword(k: string) {
    setKeywords(list.filter((x) => x !== k));
  }

  const dirty =
    list.length !== baseline.length || list.some((k, i) => k !== baseline[i]);

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Label className="text-sm">
          Roles / keywords you&apos;re searching for
        </Label>
        <p className="text-xs text-muted-foreground">
          These are the search terms used to query job boards each run — e.g.
          &quot;software engineer intern&quot;, &quot;machine learning
          intern&quot;.
        </p>
        <div className="flex flex-wrap gap-2">
          {list.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No roles yet — add one below.
            </p>
          )}
          {list.map((k) => (
            <Badge key={k} variant="secondary" className="gap-1 py-1 pl-2.5 pr-1 text-sm">
              {k}
              <button
                type="button"
                onClick={() => removeKeyword(k)}
                className="ml-1 rounded-full p-0.5 hover:bg-muted-foreground/20"
                aria-label={`Remove ${k}`}
              >
                <X className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
        <div className="flex items-center gap-2 pt-1">
          <Input
            value={manual}
            onChange={(e) => setManual(e.target.value)}
            placeholder="Add a role or keyword…"
            className="max-w-xs"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addKeyword(manual);
                setManual("");
              }
            }}
          />
          <Button
            variant="outline"
            size="sm"
            className="gap-1"
            onClick={() => {
              addKeyword(manual);
              setManual("");
            }}
            disabled={!manual.trim()}
          >
            <Plus className="size-4" /> Add
          </Button>
        </div>
      </div>

      <div className="space-y-2 rounded-lg border p-4">
        <Label className="text-sm">Suggest roles with AI</Label>
        <p className="text-xs text-muted-foreground">
          Describe the kind of work you want — a couple of role titles, or
          just what you&apos;d like to work on — and get suggested search
          keywords to add.
        </p>
        <Textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="e.g. backend or platform engineering roles, also open to anything hands-on with LLMs/RAG"
          className="min-h-20"
        />
        <div className="flex items-center gap-2">
          <ProviderSelect value={provider} onChange={setProvider} className="h-8 w-44 text-xs" />
          <Button
            size="sm"
            className="gap-2"
            onClick={() => suggest.mutate()}
            disabled={!description.trim() || suggest.isPending}
          >
            {suggest.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Sparkles className="size-4" />
            )}
            Suggest
          </Button>
        </div>
        {suggestions.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-2">
            {suggestions.map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => {
                  addKeyword(k);
                  setSuggestions((s) => s.filter((x) => x !== k));
                }}
                className="rounded-full border border-dashed px-3 py-1 text-sm text-muted-foreground hover:border-solid hover:text-foreground"
              >
                <Plus className="mr-1 inline size-3" />
                {k}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex justify-end">
        <Button onClick={() => save.mutate(list)} disabled={!dirty || save.isPending}>
          {save.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
          Save
        </Button>
      </div>
    </div>
  );
}

function NewStoryDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onSaved: (name: string) => void;
}) {
  const [description, setDescription] = useState("");
  const [provider, setProvider] = useState<string | null>(null);
  const [filename, setFilename] = useState("");
  const [draft, setDraft] = useState<string | null>(null);

  const generate = useMutation({
    mutationFn: () =>
      api.generateStory({
        description: description.trim(),
        provider: provider ?? undefined,
      }),
    onSuccess: (r) => {
      setFilename(r.filename);
      setDraft(r.text);
    },
    onError: (e) => toast.error(String(e)),
  });

  const save = useMutation({
    mutationFn: (text: string) => api.putStory(filename, text),
    onSuccess: () => {
      toast.success(`Saved ${filename}.md`);
      onSaved(filename);
      reset();
      onOpenChange(false);
    },
    onError: (e) => toast.error(String(e)),
  });

  function reset() {
    setDescription("");
    setDraft(null);
    setFilename("");
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>New story</DialogTitle>
        </DialogHeader>
        {draft === null ? (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label className="text-sm">Describe the story</Label>
              <Textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="e.g. At UBS I built a Splunk + ServiceNow monitoring dashboard for 30+ teams that cut detection time 60%…"
                className="min-h-32"
              />
            </div>
            <div className="flex items-center gap-2">
              <Label className="text-sm">Model</Label>
              <ProviderSelect
                value={provider}
                onChange={setProvider}
                className="h-8 w-44 text-xs"
              />
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Label className="text-sm">Filename</Label>
              <Input
                value={filename}
                onChange={(e) => setFilename(e.target.value)}
                className="w-64 font-mono text-xs"
              />
              <span className="text-xs text-muted-foreground">.md</span>
            </div>
            <NewStoryEditor
              draft={draft}
              onSave={(text) => save.mutate(text)}
            />
            <p className="text-xs text-muted-foreground">
              Review the draft, edit if needed, then Save in the editor above.
            </p>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          {draft === null && (
            <Button
              onClick={() => generate.mutate()}
              disabled={!description.trim() || generate.isPending}
              className="gap-2"
            >
              {generate.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Sparkles className="size-4" />
              )}
              Draft story
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function NewStoryEditor({
  draft,
  onSave,
}: {
  draft: string;
  onSave: (text: string) => void;
}) {
  const [value, setValue] = useState(draft);
  return (
    <TextEditor
      value={value}
      onValueChange={setValue}
      baseline=""
      language="markdown"
      minHeight="min-h-[40svh]"
      onSave={async (text) => onSave(text)}
    />
  );
}
