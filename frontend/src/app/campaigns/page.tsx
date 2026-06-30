"use client";

import useSWR from "swr";
import { useState } from "react";
import AppShell from "@/components/AppShell";
import { Panel, Button, Spinner, EmptyState } from "@/components/ui";
import { api, fetcher, type Campaign, type Paginated } from "@/lib/api";

function FunnelStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-center">
      <div className="font-mono text-lg font-semibold tabular-nums text-mist-100">{value}</div>
      <div className="font-mono text-[10px] uppercase tracking-wider text-mist-500">{label}</div>
    </div>
  );
}

function CampaignCard({ c, onToggle }: { c: Campaign; onToggle: () => void }) {
  const openRate = c.stat_emails_sent
    ? Math.round((c.stat_emails_opened / c.stat_emails_sent) * 100)
    : 0;
  const replyRate = c.stat_emails_sent
    ? Math.round((c.stat_replies / c.stat_emails_sent) * 100)
    : 0;
  const isActive = c.status === "active";

  return (
    <div className="rounded-panel border border-ink-600/60 bg-ink-900 p-5 shadow-panel">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h3 className="font-medium text-mist-100">{c.name}</h3>
          <div className="mt-1 flex items-center gap-2">
            {isActive ? (
              <span className="flex items-center gap-1.5 font-mono text-xs text-signal">
                <span className="live-dot" aria-hidden /> active
              </span>
            ) : (
              <span className="font-mono text-xs text-mist-500">{c.status}</span>
            )}
          </div>
        </div>
        <Button variant={isActive ? "default" : "signal"} onClick={onToggle}>
          {isActive ? "Pause" : "Activate"}
        </Button>
      </div>

      <div className="grid grid-cols-5 gap-2 border-t border-ink-700/60 pt-4">
        <FunnelStat label="Leads" value={c.stat_leads_added} />
        <FunnelStat label="Sent" value={c.stat_emails_sent} />
        <FunnelStat label={`Open ${openRate}%`} value={c.stat_emails_opened} />
        <FunnelStat label={`Reply ${replyRate}%`} value={c.stat_replies} />
        <FunnelStat label="Meetings" value={c.stat_meetings} />
      </div>
    </div>
  );
}

export default function CampaignsPage() {
  const { data, isLoading, mutate } = useSWR<Paginated<Campaign>>(
    "/campaigns?page=1&page_size=50",
    fetcher,
  );
  const [busy, setBusy] = useState<string | null>(null);

  const toggle = async (c: Campaign) => {
    setBusy(c.id);
    try {
      if (c.status === "active") await api.pauseCampaign(c.id);
      else await api.activateCampaign(c.id);
      await mutate();
    } finally {
      setBusy(null);
    }
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-8 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-mist-100">Campaigns</h1>
          <p className="mt-1 text-sm text-mist-500">
            Activate a campaign and the agent begins researching, writing, and sending
            autonomously.
          </p>
        </header>

        {isLoading ? (
          <Spinner />
        ) : !data || data.items.length === 0 ? (
          <Panel>
            <EmptyState message="No campaigns yet. Create one via the API or seed data, then activate it here to start the agent." />
          </Panel>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {data.items.map((c) => (
              <CampaignCard key={c.id} c={c} onToggle={() => toggle(c)} />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
