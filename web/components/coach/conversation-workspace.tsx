"use client";

import { useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Bookmark,
  Loader2,
  MessageSquarePlus,
  Mic,
  MoreVertical,
  Paperclip,
  Pencil,
  Play,
  SendHorizontal,
  Sparkles,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type {
  Application,
  ChatMessage,
  ChatMode,
  ChatSessionDetail,
} from "@/lib/types";
import { Markdown } from "@/components/coach/markdown";
import { GroundPicker } from "@/components/coach/ground-picker";
import { SimulatedChip } from "@/components/demo-banner";

interface ModeCopy {
  newLabel: string;
  newIcon: typeof MessageSquarePlus;
  composerPlaceholder: string;
  emptyTitle: string;
  emptyBody: string;
  threadHint: string;
}

const COPY: Record<ChatMode, ModeCopy> = {
  chat: {
    newLabel: "New chat",
    newIcon: MessageSquarePlus,
    composerPlaceholder:
      "Ask anything — Enter to send, Shift+Enter for a new line",
    emptyTitle: "Your career Coach",
    emptyBody:
      "Ask about your strongest projects, draft scholarship or behavioral answers in your voice, or add job context to prep for a specific role. Everything stays anchored to your real experience.",
    threadHint: "Talk about your profile, draft answers, prep for interviews.",
  },
  interview: {
    newLabel: "New interview",
    newIcon: Mic,
    composerPlaceholder:
      "Type your answer — Enter to send, Shift+Enter for a new line",
    emptyTitle: "Mock interview",
    emptyBody:
      "Add the job you're interviewing for, then start. The interviewer asks one question at a time, then gives grounded feedback and a model answer before moving on.",
    threadHint: "One question at a time, with coached feedback.",
  },
};

export function ConversationWorkspace({ mode }: { mode: ChatMode }) {
  const qc = useQueryClient();
  const copy = COPY[mode];
  const [pickedId, setPickedId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [saveFor, setSaveFor] = useState<ChatMessage | null>(null);

  const sessions = useQuery({
    queryKey: ["chat", "sessions", mode],
    queryFn: () => api.listChatSessions(mode),
  });

  const apps = useQuery({
    queryKey: ["applications", "all"],
    queryFn: () => api.listApplications(),
  });

  const activeId =
    pickedId ??
    (sessions.data && sessions.data.length > 0 ? sessions.data[0].id : null);
  const setActiveId = setPickedId;

  const detail = useQuery({
    queryKey: ["chat", "session", activeId],
    queryFn: () => api.getChatSession(activeId as number),
    enabled: activeId != null,
  });

  function invalidateSessions() {
    qc.invalidateQueries({ queryKey: ["chat", "sessions"] });
  }

  const createSession = useMutation({
    mutationFn: () => api.createChatSession({ mode }),
    onSuccess: (s) => {
      invalidateSessions();
      setActiveId(s.id);
    },
    onError: (e) => toast.error(String(e)),
  });

  const renameSession = useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) =>
      api.renameChatSession(id, title),
    onSuccess: invalidateSessions,
    onError: (e) => toast.error(String(e)),
  });

  const deleteSession = useMutation({
    mutationFn: (id: number) => api.deleteChatSession(id),
    onSuccess: (_d, id) => {
      invalidateSessions();
      qc.removeQueries({ queryKey: ["chat", "session", id] });
      if (activeId === id) setActiveId(null);
    },
    onError: (e) => toast.error(String(e)),
  });

  const setGrounding = useMutation({
    mutationFn: ({ id, appId }: { id: number; appId: number | null }) =>
      api.updateChatSession(id, { application_id: appId }),
    onSuccess: (_d, { id }) => {
      qc.invalidateQueries({ queryKey: ["chat", "session", id] });
      invalidateSessions();
    },
    onError: (e) => toast.error(String(e)),
  });

  const sendMessage = useMutation({
    mutationFn: ({ id, content }: { id: number; content: string }) =>
      api.sendChatMessage(id, content),
    onMutate: async ({ id, content }) => {
      await qc.cancelQueries({ queryKey: ["chat", "session", id] });
      const prev = qc.getQueryData<ChatSessionDetail>(["chat", "session", id]);
      if (prev) {
        const optimistic: ChatMessage = {
          id: -Date.now(),
          role: "user",
          content,
          created_at: new Date().toISOString(),
        };
        qc.setQueryData<ChatSessionDetail>(["chat", "session", id], {
          ...prev,
          messages: [...prev.messages, optimistic],
        });
      }
      return { prev };
    },
    onError: (e, { id }, ctx) => {
      if (ctx?.prev) qc.setQueryData(["chat", "session", id], ctx.prev);
      toast.error(`Coach failed: ${String(e)}`);
    },
    onSuccess: (_d, { id }) => {
      qc.invalidateQueries({ queryKey: ["chat", "session", id] });
      invalidateSessions();
    },
  });

  const kickoff = useMutation({
    mutationFn: (id: number) => api.kickoffInterview(id),
    onSuccess: (_d, id) => {
      qc.invalidateQueries({ queryKey: ["chat", "session", id] });
      invalidateSessions();
    },
    onError: (e) => toast.error(String(e)),
  });

  function handleSend() {
    const content = draft.trim();
    if (!content || activeId == null || sendMessage.isPending) return;
    sendMessage.mutate({ id: activeId, content });
    setDraft("");
  }

  const session = detail.data?.session;
  const messages = detail.data?.messages ?? [];
  const NewIcon = copy.newIcon;
  const interviewNotStarted =
    mode === "interview" && session != null && messages.length === 0;

  return (
    <div className="mx-auto flex h-full min-h-0 max-w-7xl gap-4">
      {/* Session sidebar */}
      <aside className="flex w-60 min-h-0 shrink-0 flex-col rounded-xl border border-border bg-card">
        <div className="border-b border-border p-3">
          <Button
            className="w-full justify-start gap-2"
            onClick={() => createSession.mutate()}
            disabled={createSession.isPending}
          >
            <NewIcon className="size-4" />
            {copy.newLabel}
          </Button>
        </div>
        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-1 p-2">
            {sessions.isLoading ? (
              <Skeleton className="h-9 w-full" />
            ) : (sessions.data ?? []).length === 0 ? (
              <p className="px-2 py-6 text-center text-xs text-muted-foreground">
                No conversations yet.
              </p>
            ) : (
              (sessions.data ?? []).map((s) => (
                <div
                  key={s.id}
                  className={cn(
                    "group flex items-center gap-1 rounded-lg pr-1 transition-colors",
                    s.id === activeId
                      ? "bg-sidebar-accent"
                      : "hover:bg-sidebar-accent/50",
                  )}
                >
                  <button
                    onClick={() => setActiveId(s.id)}
                    className="min-w-0 flex-1 px-2 py-2 text-left"
                  >
                    <div className="truncate text-sm font-medium">
                      {s.title}
                    </div>
                    {s.application_label && (
                      <div className="truncate text-[11px] text-primary">
                        {s.application_label}
                      </div>
                    )}
                  </button>
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7 shrink-0 opacity-0 group-hover:opacity-100"
                        />
                      }
                    >
                      <MoreVertical className="size-3.5" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        onClick={() => {
                          const t = window.prompt("Rename", s.title);
                          if (t && t.trim())
                            renameSession.mutate({ id: s.id, title: t.trim() });
                        }}
                      >
                        <Pencil className="mr-2 size-3.5" /> Rename
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        className="text-destructive"
                        onClick={() => deleteSession.mutate(s.id)}
                      >
                        <Trash2 className="mr-2 size-3.5" /> Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              ))
            )}
          </div>
        </ScrollArea>
      </aside>

      {/* Conversation */}
      <section className="flex min-h-0 min-w-0 flex-1 flex-col rounded-xl border border-border bg-card">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 truncate font-heading text-sm font-semibold">
              <span className="truncate">{session?.title ?? copy.emptyTitle}</span>
              <SimulatedChip />
            </h2>
            <p className="text-[11px] text-muted-foreground">
              {copy.threadHint}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {session && (
              <GroundPicker
                apps={apps.data ?? []}
                applicationId={session.application_id}
                applicationLabel={session.application_label}
                disabled={setGrounding.isPending}
                onChange={(appId) =>
                  setGrounding.mutate({ id: session.id, appId })
                }
              />
            )}
            <AnswerBank apps={apps.data ?? []} />
          </div>
        </header>

        <ScrollArea className="min-h-0 flex-1">
          <div className="mx-auto flex max-w-3xl flex-col gap-4 p-4">
            {activeId == null ? (
              <EmptyState copy={copy} />
            ) : detail.isLoading ? (
              <>
                <Skeleton className="h-16 w-2/3" />
                <Skeleton className="ml-auto h-10 w-1/2" />
              </>
            ) : interviewNotStarted ? (
              <InterviewStart
                grounded={session?.application_id != null}
                pending={kickoff.isPending}
                onStart={() => activeId != null && kickoff.mutate(activeId)}
              />
            ) : messages.length === 0 ? (
              <EmptyState copy={copy} />
            ) : (
              messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  msg={m}
                  onSave={() => setSaveFor(m)}
                />
              ))
            )}
            {(sendMessage.isPending || kickoff.isPending) && <ThinkingBubble />}
          </div>
        </ScrollArea>

        {/* Composer */}
        <div
          id="tour-coach-composer"
          className="shrink-0 border-t border-border p-3"
        >
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={
                activeId == null
                  ? `Start a ${copy.newLabel.toLowerCase()} to begin…`
                  : interviewNotStarted
                    ? "Start the interview first…"
                    : copy.composerPlaceholder
              }
              disabled={
                activeId == null ||
                interviewNotStarted ||
                sendMessage.isPending
              }
              className="max-h-40 min-h-[44px] resize-none"
              rows={1}
            />
            <Button
              size="icon"
              className="size-11 shrink-0"
              onClick={handleSend}
              disabled={
                activeId == null ||
                interviewNotStarted ||
                sendMessage.isPending ||
                !draft.trim()
              }
            >
              {sendMessage.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <SendHorizontal className="size-4" />
              )}
            </Button>
          </div>
        </div>
      </section>

      <SaveAnswerDialog
        key={saveFor?.id ?? "none"}
        msg={saveFor}
        onClose={() => setSaveFor(null)}
        onSaved={() => qc.invalidateQueries({ queryKey: ["chat", "answers"] })}
      />
    </div>
  );
}

function EmptyState({ copy }: { copy: ModeCopy }) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-center">
      <span className="brand-gradient flex size-12 items-center justify-center rounded-xl shadow-lg shadow-primary/25">
        <Sparkles className="size-6 text-white" />
      </span>
      <h3 className="font-heading text-lg font-semibold">{copy.emptyTitle}</h3>
      <p className="max-w-md text-sm text-muted-foreground">{copy.emptyBody}</p>
    </div>
  );
}

function InterviewStart({
  grounded,
  pending,
  onStart,
}: {
  grounded: boolean;
  pending: boolean;
  onStart: () => void;
}) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-center">
      <span className="brand-gradient flex size-12 items-center justify-center rounded-xl shadow-lg shadow-primary/25">
        <Mic className="size-6 text-white" />
      </span>
      <h3 className="font-heading text-lg font-semibold">Ready when you are</h3>
      <p className="max-w-md text-sm text-muted-foreground">
        {grounded
          ? "Questions will be tailored to the job context above."
          : "Tip: add job context above so questions match the role. You can also start a general behavioral interview."}
      </p>
      <Button onClick={onStart} disabled={pending} className="gap-2">
        {pending ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <Play className="size-4" />
        )}
        Start interview
      </Button>
    </div>
  );
}

function MessageBubble({
  msg,
  onSave,
}: {
  msg: ChatMessage;
  onSave: () => void;
}) {
  const isUser = msg.role === "user";
  return (
    <div className={cn("flex flex-col gap-1", isUser && "items-end")}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-4 py-2.5",
          isUser
            ? "bg-primary text-primary-foreground"
            : "border border-border bg-background",
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">
            {msg.content}
          </p>
        ) : (
          <Markdown>{msg.content}</Markdown>
        )}
      </div>
      {!isUser && (
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1.5 px-2 text-xs text-muted-foreground"
          onClick={onSave}
        >
          <Bookmark className="size-3" /> Save to answer bank
        </Button>
      )}
    </div>
  );
}

function ThinkingBubble() {
  return (
    <div className="flex w-fit items-center gap-2 rounded-2xl border border-border bg-background px-4 py-3 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" />
      Coach is thinking…
    </div>
  );
}

function SaveAnswerDialog({
  msg,
  onClose,
  onSaved,
}: {
  msg: ChatMessage | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [tags, setTags] = useState("");

  const save = useMutation({
    mutationFn: () =>
      api.saveAnswer({
        content: msg?.content ?? "",
        title: title.trim() || undefined,
        prompt: prompt.trim() || undefined,
        tags: tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        source_message_id: msg && msg.id > 0 ? msg.id : undefined,
      }),
    onSuccess: () => {
      toast.success("Saved to answer bank");
      onSaved();
      onClose();
    },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <Dialog open={msg != null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Save to answer bank</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label className="text-sm">Title</Label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Why this company"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm">Prompt / question (optional)</Label>
            <Input
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="The question this answers"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm">Tags (comma-separated)</Label>
            <Input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="behavioral, scholarship"
            />
          </div>
          <div className="max-h-40 overflow-auto rounded-lg border border-border bg-muted/40 p-3 text-xs">
            {msg?.content}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AnswerBank({ apps }: { apps: Application[] }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const answers = useQuery({
    queryKey: ["chat", "answers", "all"],
    queryFn: () => api.listSavedAnswers(),
    enabled: open,
  });

  const del = useMutation({
    mutationFn: (id: number) => api.deleteSavedAnswer(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat", "answers"] }),
    onError: (e) => toast.error(String(e)),
  });

  const attach = useMutation({
    mutationFn: ({ id, appId }: { id: number; appId: number }) =>
      api.attachAnswer(id, appId),
    onSuccess: (_d, { appId }) => {
      toast.success("Attached to application");
      qc.invalidateQueries({ queryKey: ["chat", "answers"] });
      qc.invalidateQueries({ queryKey: ["application", appId] });
    },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        render={
          <Button variant="outline" size="sm" className="shrink-0 gap-2" />
        }
      >
        <Bookmark className="size-3.5" /> Answer bank
      </SheetTrigger>
      <SheetContent className="flex w-full flex-col gap-0 sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Answer bank</SheetTitle>
        </SheetHeader>
        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-3 p-4">
            {answers.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : (answers.data ?? []).length === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground">
                No saved answers yet. Save a Coach reply to reuse it later.
              </p>
            ) : (
              (answers.data ?? []).map((a) => (
                <div
                  key={a.id}
                  className="rounded-xl border border-border bg-background p-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">
                        {a.title || a.prompt || "Untitled"}
                      </div>
                      {a.tags.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {a.tags.map((t) => (
                            <Badge
                              key={t}
                              variant="outline"
                              className="text-[10px]"
                            >
                              {t}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7 shrink-0"
                      onClick={() => del.mutate(a.id)}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                  <p className="mt-2 line-clamp-4 whitespace-pre-wrap text-xs text-muted-foreground">
                    {a.content}
                  </p>
                  <div className="mt-3">
                    <Select
                      onValueChange={(v) =>
                        v && attach.mutate({ id: a.id, appId: Number(v) })
                      }
                    >
                      <SelectTrigger className="w-full text-xs">
                        <span className="flex items-center gap-1.5">
                          <Paperclip className="size-3" />
                          <SelectValue placeholder="Attach to application…" />
                        </span>
                      </SelectTrigger>
                      <SelectContent>
                        {apps.map((app) => (
                          <SelectItem key={app.id} value={String(app.id)}>
                            {app.company} — {app.title}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              ))
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
