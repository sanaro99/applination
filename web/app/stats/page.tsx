"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Marquee } from "@/components/ui/marquee";
import { NumberTicker } from "@/components/ui/number-ticker";
import { api } from "@/lib/api";

const PIE_COLORS = [
  "var(--color-chart-1)",
  "var(--color-chart-2)",
  "var(--color-chart-3)",
  "var(--color-chart-4)",
  "var(--color-chart-5)",
];

const AXIS_COLOR = "var(--color-muted-foreground)";
const GRID_COLOR = "var(--color-border)";
const TOOLTIP_STYLE: React.CSSProperties = {
  background: "var(--color-popover)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius-md)",
  color: "var(--color-popover-foreground)",
};

export default function StatsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["stats"],
    queryFn: () => api.getStats(),
    // Aggregates only change after a run completes; no need to poll the heavy
    // chart page. It refetches when the cache goes stale on the next visit.
    refetchInterval: false,
  });

  if (isLoading || !data) {
    return <Skeleton className="h-[80svh]" />;
  }

  const statusEntries = Object.entries(data.by_status).filter(([, v]) => v > 0);
  const sourceEntries = Object.entries(data.by_source).filter(([, v]) => v > 0);
  const funnel = [
    { name: "Generated", value: data.by_status.generated ?? 0 },
    { name: "Applied", value: data.by_status.applied ?? 0 },
    { name: "Interviewing", value: data.by_status.interviewing ?? 0 },
    { name: "Offer", value: data.by_status.offer ?? 0 },
  ];

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Applications" value={data.total_applications} />
        <StatTile label="Average score" value={data.avg_score} />
        <StatTile label="Runs total" value={data.runs_total} />
        <StatTile label="Runs (30d)" value={data.runs_30d} />
      </div>

      {data.top_companies.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top companies</CardTitle>
          </CardHeader>
          <CardContent className="overflow-hidden">
            <Marquee pauseOnHover className="[--duration:35s]">
              {data.top_companies.map((c) => (
                <div
                  key={c.company}
                  className="mx-2 flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-sm"
                >
                  <span className="font-medium">{c.company}</span>
                  <span className="text-xs text-muted-foreground">
                    {c.count}×
                  </span>
                </div>
              ))}
            </Marquee>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Applications per day</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            {data.daily.length === 0 ? (
              <Empty />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.daily}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
                  <XAxis dataKey="date" stroke={AXIS_COLOR} fontSize={10} />
                  <YAxis stroke={AXIS_COLOR} fontSize={10} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ stroke: GRID_COLOR }} />
                  <Line
                    type="monotone"
                    dataKey="count"
                    stroke="var(--color-chart-1)"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Score distribution</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.score_buckets}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
                <XAxis dataKey="bucket" stroke={AXIS_COLOR} fontSize={10} />
                <YAxis stroke={AXIS_COLOR} fontSize={10} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ fill: "var(--color-muted)", opacity: 0.4 }}
                />
                <Bar dataKey="count" fill="var(--color-chart-1)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">By source</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            {sourceEntries.length === 0 ? (
              <Empty />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={sourceEntries.map(([name, value]) => ({
                      name,
                      value,
                    }))}
                    dataKey="value"
                    outerRadius={90}
                    label
                  >
                    {sourceEntries.map((_, i) => (
                      <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Application funnel</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={funnel} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
                <XAxis type="number" stroke={AXIS_COLOR} fontSize={10} />
                <YAxis
                  type="category"
                  dataKey="name"
                  stroke={AXIS_COLOR}
                  fontSize={10}
                />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ fill: "var(--color-muted)", opacity: 0.4 }}
                />
                <Bar dataKey="value" fill="var(--color-chart-5)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Status totals</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {statusEntries.map(([k, v]) => (
            <div
              key={k}
              className="rounded-md border border-border bg-card px-3 py-1.5 text-sm capitalize"
            >
              {k} · <span className="font-mono">{v}</span>
            </div>
          ))}
          {statusEntries.length === 0 && <Empty />}
        </CardContent>
      </Card>
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-semibold tabular-nums">
          <NumberTicker value={value} />
        </div>
      </CardContent>
    </Card>
  );
}

function Empty() {
  return (
    <p className="flex h-full items-center justify-center text-sm text-muted-foreground">
      No data yet.
    </p>
  );
}
