"use client";

import useSWR from "swr";
import { useState } from "react";
import { formatDistanceToNow, parseISO } from "date-fns";
import AppShell from "@/components/AppShell";
import { Panel, ClassificationTag, Button, Spinner, EmptyState } from "@/components/ui";
import { api, fetcher, type Reply, type Paginated } from "@/lib/api";

function SentimentBar({ score }: { score: number | null }) {
  if (score === null) return null;
  const pct = ((score + 1) / 2) * 100;
  const tone = score > 0.2 ? "bg-signal" : score < -0.2 ? "bg-coral" : "bg-amber";
  return (
    <div className="flex items-center gap-2">
      <span className="font-mono text-[10px] text-mist-600">sentiment</span>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-ink-700">
        <div className={`h-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ReplyCard({ reply, onReviewed }: { reply: Reply; onReviewed: () => void }) {
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const confirm = async () => {
    setBusy(true);
    try {
      await api.reviewReply(reply.id);
      onReviewed();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-panel border border-ink-600/60 bg-ink-900 p-5 shadow-panel">
      <div className="mb-3 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate font-medium text-mist-100">
              {reply.from_name || reply.from_email}
            </span>
            <ClassificationTag value={reply.classification} />
            {reply.classification_confidence !== null && (
              <span className="font-mono text-[10px] text-mist-600">
                {Math.round(reply.classification_confidence * 100)}% conf
              </span>
            )}
          </div>
          <div className="truncate font-mono text-xs text-mist-500">
            {reply.subject || "(no subject)"} ·{" "}
            {formatDistanceToNow(parseISO(reply.received_at), { addSuffix: true })}
          </div>
        </div>
        <SentimentBar score={reply.sentiment_score} />
      </div>

      {reply.ai_summary && (
        <div className="mb-3 rounded border border-ink-700/60 bg-ink-950/60 px-3 py-2">
          <span className="font-mono text-[10px] uppercase tracking-wider text-signal-dim">
            agent read
          </span>
          <p className="mt-1 text-sm text-mist-300">{reply.ai_summary}</p>
        </div>
      )}

      <p className={`text-sm text-mist-400 ${expanded ? "" : "line-clamp-2"}`}>
        {reply.body_text}
      </p>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="mt-1 font-mono text-xs text-mist-600 hover:text-mist-300"
      >
        {expanded ? "collapse" : "expand"}
      </button>

      <div className="mt-4 flex items-center gap-2 border-t border-ink-700/60 pt-3">
        <Button variant="signal" onClick={confirm} disabled={busy}>
          {busy ? "Saving…" : "Confirm & clear"}
        </Button>
        <span className="font-mono text-xs text-mist-600">
          The agent has already acted — confirming clears it from the queue.
        </span>
      </div>
    </div>
  );
}

export default function RepliesPage() {
  const { data, isLoading, mutate } = useSWR<Paginated<Reply>>(
    "/replies/pending-review",
    fetcher,
    { refreshInterval: 20000 },
  );

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl px-8 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-mist-100">Reply Queue</h1>
          <p className="mt-1 flex items-center gap-2 text-sm text-mist-500">
            <span className="live-dot" aria-hidden />
            Replies the agent flagged for a human glance. {data ? `${data.total} pending.` : ""}
          </p>
        </header>

        {isLoading ? (
          <Spinner />
        ) : !data || data.items.length === 0 ? (
          <Panel>
            <EmptyState message="Queue is clear. The agent is handling replies on its own — anything needing judgment will surface here." />
          </Panel>
        ) : (
          <div className="flex flex-col gap-4">
            {data.items.map((r) => (
              <ReplyCard key={r.id} reply={r} onReviewed={() => mutate()} />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
