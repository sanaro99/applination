"use client";

import Link from "next/link";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useState } from "react";

import type { Application, ApplicationStatus } from "@/lib/types";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { ScoreChip, STATUSES } from "@/components/status-badge";
import { cn } from "@/lib/utils";

const COLUMN_LABELS: Record<ApplicationStatus, string> = {
  generated: "Generated",
  applied: "Applied",
  interviewing: "Interviewing",
  rejected: "Rejected",
  offer: "Offer",
  archived: "Archived",
};

export function ApplicationsKanban({
  applications,
}: {
  applications: Application[];
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );
  const qc = useQueryClient();
  const update = useMutation({
    mutationFn: ({ id, status }: { id: number; status: ApplicationStatus }) =>
      api.patchApplication(id, { status }),
    onMutate: async ({ id, status }) => {
      await qc.cancelQueries({ queryKey: ["applications"] });
      const prev = qc.getQueryData<Application[]>(["applications"]);
      if (prev) {
        qc.setQueryData<Application[]>(
          ["applications"],
          prev.map((a) => (a.id === id ? { ...a, status } : a)),
        );
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["applications"], ctx.prev);
      toast.error("Failed to update status");
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["applications"] }),
  });

  const [activeId, setActiveId] = useState<number | null>(null);
  const activeApp = applications.find((a) => a.id === activeId);

  const grouped: Record<ApplicationStatus, Application[]> = {
    generated: [],
    applied: [],
    interviewing: [],
    rejected: [],
    offer: [],
    archived: [],
  };
  for (const a of applications) grouped[a.status].push(a);

  function handleDragStart(e: DragStartEvent) {
    setActiveId(Number(e.active.id));
  }

  function handleDragEnd(e: DragEndEvent) {
    setActiveId(null);
    if (!e.over) return;
    const id = Number(e.active.id);
    const target = e.over.id as ApplicationStatus;
    const current = applications.find((a) => a.id === id);
    if (!current || current.status === target) return;
    update.mutate({ id, status: target });
  }

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="grid auto-rows-fr grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {STATUSES.map((s) => (
          <KanbanColumn key={s} status={s} items={grouped[s]} />
        ))}
      </div>
      <DragOverlay>
        {activeApp ? <KanbanCard app={activeApp} dragging /> : null}
      </DragOverlay>
    </DndContext>
  );
}

function KanbanColumn({
  status,
  items,
}: {
  status: ApplicationStatus;
  items: Application[];
}) {
  const { setNodeRef, isOver } = useDroppable({ id: status });
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex h-full min-h-[300px] flex-col rounded-xl border border-border bg-muted/30 p-3 transition-colors",
        isOver && "border-primary/60 bg-primary/5",
      )}
    >
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold capitalize">
          {COLUMN_LABELS[status]}
        </h3>
        <span className="rounded-full bg-background px-2 py-0.5 text-xs text-muted-foreground">
          {items.length}
        </span>
      </div>
      <div className="flex flex-col gap-2 overflow-auto">
        {items.map((a) => (
          <KanbanCard key={a.id} app={a} />
        ))}
      </div>
    </div>
  );
}

function KanbanCard({
  app,
  dragging,
}: {
  app: Application;
  dragging?: boolean;
}) {
  const { setNodeRef, listeners, attributes, transform, isDragging } =
    useDraggable({ id: app.id });
  const style = transform
    ? { transform: `translate(${transform.x}px, ${transform.y}px)` }
    : undefined;
  return (
    <div ref={setNodeRef} style={style} {...listeners} {...attributes}>
      <Card
        className={cn(
          "cursor-grab p-3 transition-shadow hover:shadow-md",
          (isDragging || dragging) && "opacity-60 shadow-lg",
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <Link
            href={`/applications/${app.id}`}
            className="min-w-0 text-sm font-medium hover:underline"
            onPointerDown={(e) => e.stopPropagation()}
          >
            {app.company}
          </Link>
          <ScoreChip score={app.match_score} />
        </div>
        <p className="mt-1 truncate text-xs text-muted-foreground">
          {app.title}
        </p>
      </Card>
    </div>
  );
}
