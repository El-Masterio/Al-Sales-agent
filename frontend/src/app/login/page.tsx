"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, tokenStore } from "@/lib/api";
import { Button } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      const tokens = await api.login(email, password);
      tokenStore.set(tokens.access_token, tokens.refresh_token);
      router.replace("/dashboard");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center panel-grid px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-3">
          <span className="live-dot" aria-hidden />
          <div>
            <div className="font-mono text-lg font-semibold tracking-tight text-mist-100">
              SALES&nbsp;AGENT
            </div>
            <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-signal-dim">
              operator console
            </div>
          </div>
        </div>

        <div className="rounded-panel border border-ink-600/60 bg-ink-900 p-6 shadow-panel">
          <h1 className="mb-1 text-lg font-semibold text-mist-100">Sign in</h1>
          <p className="mb-5 text-sm text-mist-500">
            Access the agent&apos;s mission control.
          </p>

          <label className="mb-1 block font-mono text-xs uppercase tracking-wider text-mist-400">
            Email
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            className="mb-4 w-full rounded border border-ink-600 bg-ink-950 px-3 py-2 text-sm text-mist-100 outline-none focus:border-signal/50"
            placeholder="you@company.com"
          />

          <label className="mb-1 block font-mono text-xs uppercase tracking-wider text-mist-400">
            Password
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            className="mb-5 w-full rounded border border-ink-600 bg-ink-950 px-3 py-2 text-sm text-mist-100 outline-none focus:border-signal/50"
            placeholder="••••••••"
          />

          {error && <p className="mb-4 text-sm text-coral">{error}</p>}

          <Button variant="signal" onClick={submit} disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </div>
      </div>
    </div>
  );
}
