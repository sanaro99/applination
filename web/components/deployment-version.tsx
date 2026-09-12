"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

/** Small, unobtrusive support signal: identifies the exact deployed image. */
export function DeploymentVersion() {
  const { data } = useQuery({
    queryKey: ["deployment-version"],
    queryFn: api.version,
    staleTime: Infinity,
  });

  if (!data) return null;
  return (
    <p className="text-xs text-muted-foreground">
      Applination v{data.version} <span aria-hidden="true">·</span>{" "}
      <span className="font-mono">{data.revision}</span>
    </p>
  );
}
