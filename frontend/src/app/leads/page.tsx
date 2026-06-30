"use client";

import useSWR from "swr";
import { useState } from "react";
import { format, parseISO } from "date-fns";
import AppShell from "@/components/AppShell";
import { Panel, StatusBadge, Button, Spinner, EmptyState } from "@/components/ui";
import { api, fetcher, type Company, type Paginated } from "@/lib/api";

function IcpScore({ score }: { score: number | null }) {
  if (score === null) return <span className="font-mono text-xs text-mist-600">—</span>;
  const tone = score >= 70 ? "text-signal" : score >= 40 ? "text-amber" : "text-mist-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-700">
        <div
          className="h-full rounded-full bg-signal/70"
          style={{ width: `${score}%` }}
        />
      </div>
      <span className={`font-mono text-xs tabular-nums ${tone}`}>{score}</span>
    </div>
  );
}

export default function LeadsPage() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const query = `/companies?page=${page}&page_size=25${search ? `&search=${encodeURIComponent(search)}` : ""}`;
  const { data, isLoading, mutate } = useSWR<Paginated<Company>>(query, fetcher);
  const [researching, setResearching] = useState<string | null>(null);

  const triggerResearch = async (id: string) => {
    setResearching(id);
    try {
      await api.triggerResearch(id);
      setTimeout(() => mutate(), 1500);
    } finally {
      setResearching(null);
    }
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-8 py-8">
        <header className="mb-6 flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-mist-100">Leads</h1>
            <p className="mt-1 text-sm text-mist-500">
              {data ? `${data.total} companies in pipeline` : "Loading pipeline…"}
            </p>
          </div>
          <input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            placeholder="Search by company name…"
            className="w-72 rounded border border-ink-600 bg-ink-950 px-3 py-2 text-sm text-mist-100 outline-none focus:border-signal/50"
          />
        </header>

        <Panel>
          {isLoading ? (
            <div className="p-6">
              <Spinner />
            </div>
          ) : !data || data.items.length === 0 ? (
            <EmptyState message="No leads match this view yet. Generate leads from a campaign's ICP criteria to populate the pipeline." />
          ) : (
            <table className="w-full">
              <thead>
                <tr className="border-b border-ink-600/60 text-left">
                  {["Company", "Industry", "ICP", "Status", "Researched", ""].map((h) => (
                    <th
                      key={h}
                      className="px-5 py-3 font-mono text-[11px] uppercase tracking-wider text-mist-500"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((c) => (
                  <tr
                    key={c.id}
                    className="border-b border-ink-800/50 transition-colors hover:bg-ink-800/40"
                  >
                    <td className="px-5 py-3.5">
                      <div className="font-medium text-mist-100">{c.name}</div>
                      {c.website && (
                        <a
                          href={c.website}
                          target="_blank"
                          rel="noreferrer"
                          className="font-mono text-xs text-mist-500 hover:text-signal"
                        >
                          {c.website.replace(/^https?:\/\//, "")}
                        </a>
                      )}
                    </td>
                    <td className="px-5 py-3.5 text-sm text-mist-300">{c.industry ?? "—"}</td>
                    <td className="px-5 py-3.5">
                      <IcpScore score={c.icp_score} />
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={c.lead_status} />
                    </td>
                    <td className="px-5 py-3.5 font-mono text-xs text-mist-500">
                      {c.last_researched_at
                        ? format(parseISO(c.last_researched_at), "MMM d")
                        : "never"}
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      {!c.last_researched_at && (
                        <Button
                          variant="ghost"
                          onClick={() => triggerResearch(c.id)}
                          disabled={researching === c.id}
                        >
                          {researching === c.id ? "Queued…" : "Research"}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        {data && data.total_pages > 1 && (
          <div className="mt-4 flex items-center justify-between">
            <span className="font-mono text-xs text-mist-500">
              Page {data.page} / {data.total_pages}
            </span>
            <div className="flex gap-2">
              <Button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
                Previous
              </Button>
              <Button
                onClick={() => setPage((p) => p + 1)}
                disabled={page >= data.total_pages}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
