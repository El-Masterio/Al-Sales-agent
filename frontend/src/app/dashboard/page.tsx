"use client";

import useSWR from "swr";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { format, parseISO } from "date-fns";
import AppShell from "@/components/AppShell";
import { Panel, Spinner } from "@/components/ui";
import { fetcher, type DashboardOverview, type TimeSeriesPoint } from "@/lib/api";

function Metric({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <div className="rounded-panel border border-ink-600/60 bg-ink-900 p-5 shadow-panel">
      <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.15em] text-mist-500">
        {label}
      </div>
      <div
        className={`font-mono text-3xl font-semibold tabular-nums ${
          accent ? "text-signal" : "text-mist-100"
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-mist-500">{sub}</div>}
    </div>
  );
}

export default function DashboardPage() {
  const { data: overview } = useSWR<DashboardOverview>("/dashboard/overview", fetcher, {
    refreshInterval: 15000,
  });
  const { data: series } = useSWR<{ points: TimeSeriesPoint[] }>(
    "/dashboard/time-series?days=30",
    fetcher,
  );

  const usd = (n: number) =>
    n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${n}`;

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-8 py-8">
        <header className="mb-7 flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-mist-100">
              Mission Control
            </h1>
            <p className="mt-1 flex items-center gap-2 text-sm text-mist-500">
              <span className="live-dot" aria-hidden />
              Agent is running autonomously · metrics refresh every 15s
            </p>
          </div>
        </header>

        {!overview ? (
          <Spinner />
        ) : (
          <>
            {/* Primary metrics row */}
            <div className="mb-5 grid grid-cols-2 gap-4 lg:grid-cols-4">
              <Metric
                label="New leads today"
                value={String(overview.new_leads_today)}
                sub={`${overview.total_leads} total in pipeline`}
                accent
              />
              <Metric
                label="Emails sent today"
                value={String(overview.emails_sent_today)}
                sub={`${overview.emails_sent_total} all-time`}
              />
              <Metric
                label="Open rate"
                value={`${overview.open_rate_pct}%`}
                sub={`reply rate ${overview.reply_rate_pct}%`}
              />
              <Metric
                label="Meetings booked"
                value={String(overview.meetings_booked_today)}
                sub={`${overview.meetings_booked_total} all-time`}
                accent
              />
            </div>

            {/* Secondary row */}
            <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
              <Metric label="Revenue pipeline" value={usd(overview.revenue_pipeline_usd)} accent />
              <Metric label="Active campaigns" value={String(overview.active_campaigns)} />
              <Metric label="Reply rate" value={`${overview.reply_rate_pct}%`} />
              <Metric
                label="Emails (all-time)"
                value={String(overview.emails_sent_total)}
              />
            </div>

            {/* Activity chart */}
            <Panel title="Agent activity · 30 days">
              <div className="h-72">
                {series && series.points.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={series.points} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                      <defs>
                        <linearGradient id="g-emails" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#3ddc84" stopOpacity={0.35} />
                          <stop offset="100%" stopColor="#3ddc84" stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="g-replies" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#e8a33d" stopOpacity={0.3} />
                          <stop offset="100%" stopColor="#e8a33d" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="#1d2622" vertical={false} />
                      <XAxis
                        dataKey="date"
                        tickFormatter={(d) => format(parseISO(d), "MMM d")}
                        stroke="#3a4843"
                        tick={{ fill: "#6b7c75", fontSize: 11, fontFamily: "monospace" }}
                        tickLine={false}
                      />
                      <YAxis
                        stroke="#3a4843"
                        tick={{ fill: "#6b7c75", fontSize: 11, fontFamily: "monospace" }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <Tooltip
                        contentStyle={{
                          background: "#0f1513",
                          border: "1px solid #2a352f",
                          borderRadius: 8,
                          fontSize: 12,
                        }}
                        labelStyle={{ color: "#aab8b2", fontFamily: "monospace" }}
                        labelFormatter={(d) => format(parseISO(d as string), "MMM d, yyyy")}
                      />
                      <Area
                        type="monotone"
                        dataKey="emails_sent"
                        stroke="#3ddc84"
                        strokeWidth={2}
                        fill="url(#g-emails)"
                        name="Emails sent"
                      />
                      <Area
                        type="monotone"
                        dataKey="replies_received"
                        stroke="#e8a33d"
                        strokeWidth={2}
                        fill="url(#g-replies)"
                        name="Replies"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-full items-center justify-center text-sm text-mist-600">
                    No activity recorded yet. The agent will populate this once campaigns
                    go live.
                  </div>
                )}
              </div>
            </Panel>
          </>
        )}
      </div>
    </AppShell>
  );
}
