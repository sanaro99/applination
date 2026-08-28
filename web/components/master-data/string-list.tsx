"use client";

/**
 * A list of short strings or bullets, with add, remove and reorder.
 *
 * Reordering is real work, not polish: the tailor selects the best bullets per
 * job, and a user who wants a bullet considered first has no other way to say
 * so. dnd-kit is already a dependency and already drives the applications
 * kanban.
 */
import {
  DndContext,
  closestCenter,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

export function StringList({
  value,
  onChange,
  itemLabel,
  multiline = false,
  placeholder,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  itemLabel: string;
  multiline?: boolean;
  placeholder?: string;
}) {
  // Index-based ids are stable for the lifetime of a drag, which is all
  // dnd-kit needs, and avoid inventing keys the server would have to carry.
  const ids = value.map((_, i) => `item-${i}`);

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    onChange(arrayMove(value, ids.indexOf(String(active.id)), ids.indexOf(String(over.id))));
  };

  const set = (index: number, next: string) =>
    onChange(value.map((v, i) => (i === index ? next : v)));

  return (
    <div className="space-y-2">
      <DndContext collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={ids} strategy={verticalListSortingStrategy}>
          {value.map((item, index) => (
            <Row
              key={ids[index]}
              id={ids[index]}
              value={item}
              multiline={multiline}
              placeholder={placeholder}
              onChange={(next) => set(index, next)}
              onRemove={() => onChange(value.filter((_, i) => i !== index))}
            />
          ))}
        </SortableContext>
      </DndContext>

      <Button
        size="sm"
        variant="outline"
        className="gap-1.5"
        onClick={() => onChange([...value, ""])}
      >
        <Plus className="size-3.5" /> Add {itemLabel}
      </Button>
    </div>
  );
}

function Row({
  id,
  value,
  multiline,
  placeholder,
  onChange,
  onRemove,
}: {
  id: string;
  value: string;
  multiline: boolean;
  placeholder?: string;
  onChange: (v: string) => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition } =
    useSortable({ id });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="flex items-start gap-2"
    >
      <button
        type="button"
        className="mt-2 cursor-grab text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="Reorder"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="size-4" />
      </button>
      {multiline ? (
        <Textarea
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          className="min-h-16 flex-1 text-sm"
        />
      ) : (
        <Input
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          className="flex-1"
        />
      )}
      <Button
        size="icon"
        variant="ghost"
        className="mt-0.5 shrink-0"
        onClick={onRemove}
        aria-label="Remove"
      >
        <X className="size-4" />
      </Button>
    </div>
  );
}
