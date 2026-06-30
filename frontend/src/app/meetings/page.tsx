"use client";

import useSWR from "swr";
import { format, parseISO } from "date-fns";
import { Video, Phone, MapPin } from "lucide-react";
import AppShell from "@/components/AppShell";
import { Panel, StatusBadge, Spinner, EmptyState } from "@/components/ui";
import { fetcher, type Paginated } from "@/lib/api";

interface Meeting {
  id: string;
  title: string;
  status: string;
  starts_at: string;
  duration_minutes: number;
  location_type: string;
  meeting_url: string | null;
}

const LocationIcon = ({ type }: { type: string }) => {
  if (type === "video") return <Video size={15} className="text-signal" />;
  if (type === "phone") return <Phone size={15} className="text-mist-400" />;
  return <MapPin size={15} className="text-mist-400" />;
};

export default function MeetingsPage() {
  const { data, isLoading } = useSWR<Paginated<Meeting>>("/meetings/upcoming", fetcher);

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl px-8 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-mist-100">Meetings</h1>
          <p className="mt-1 text-sm text-mist-500">
            Booked by the agent once leads said yes. Synced to your calendar.
          </p>
        </header>

        <Panel>
          {isLoading ? (
            <div className="p-6">
              <Spinner />
            </div>
          ) : !data || data.items.length === 0 ? (
            <EmptyState message="No upcoming meetings. When a lead accepts a slot, the agent books it and it appears here." />
          ) : (
            <div className="divide-y divide-ink-800/60">
              {data.items.map((m) => (
                <div key={m.id} className="flex items-center gap-4 px-5 py-4">
                  <div className="w-20 text-center">
                    <div className="font-mono text-[11px] uppercase tracking-wider text-mist-500">
                      {format(parseISO(m.starts_at), "MMM")}
                    </div>
                    <div className="font-mono text-2xl font-semibold tabular-nums text-mist-100">
                      {format(parseISO(m.starts_at), "d")}
                    </div>
                  </div>
                  <div className="flex-1">
                    <div className="font-medium text-mist-100">{m.title}</div>
                    <div className="mt-0.5 flex items-center gap-2 font-mono text-xs text-mist-500">
                      <LocationIcon type={m.location_type} />
                      {format(parseISO(m.starts_at), "h:mm a")} · {m.duration_minutes}m
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <StatusBadge status={m.status} />
                    {m.meeting_url && (
                      <a
                        href={m.meeting_url}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded bg-signal/15 px-3 py-1.5 font-mono text-xs text-signal hover:bg-signal/25"
                      >
                        Join
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </AppShell>
  );
}
