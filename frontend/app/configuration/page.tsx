"use client";

import { useCallback, useEffect, useState } from "react";
import { useTenantPlane } from "../components/tenant";
import { Timeline, type TimelineEvent } from "../components/timeline";
import { Badge, Button, Card, Field, NeedTenant, PageHeader, inputClass, statusTone } from "../components/ui";
import { OpResult, errorText, plane } from "../lib/client";

type Ctrl = {
  desired: { message: string; version: number };
  data_config: { status: string; last_applied_version: number | null; reported_at?: string | null };
  timeline: TimelineEvent[];
};

export default function Configuration() {
  const { tenant, target, error } = useTenantPlane("control");
  const [result, setResult] = useState<OpResult | null>(null);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");
  const c = result?.ok ? (result.json as Ctrl) : null;

  const load = useCallback(async () => {
    if (target) setResult(await plane(target, "GET", `/tenants/${tenant}?limit=100`));
  }, [target, tenant]);

  useEffect(() => {
    const first = setTimeout(load, 0);
    const timer = setInterval(load, 5000);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [load]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!target) return;
    const saved = await plane(target, "PUT", `/tenants/${tenant}/configuration`, { message: draft });
    setNotice(saved.ok ? `Saved as version ${(saved.json as Ctrl)?.desired?.version}. Data applies it on its next poll.` : errorText(saved));
    if (saved.ok) setDraft("");
    load();
  }

  if (!tenant) return <NeedTenant />;
  const inSync = c && c.data_config.last_applied_version === c.desired.version;

  return (
    <>
      <PageHeader
        title="Configuration"
        description={`Desired configuration for tenant ${tenant}. You write to Control; the data plane pulls it.`}
        actions={<Button onClick={load}>Refresh</Button>}
      />
      {error && <p className="rounded-xl bg-white p-3 font-medium ring-1 ring-neutral-900">{error}</p>}
      {notice && <p className="rounded-xl bg-neutral-900 px-4 py-2.5 text-white">{notice}</p>}
      {!c ? (
        !error && <p className="text-neutral-400">{result ? errorText(result) : "loading…"}</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="Desired" subtitle="stored in Control">
            <div className="text-2xl font-semibold break-words">{c.desired.message}</div>
            <div className="text-xs text-neutral-500">version {c.desired.version}</div>
            <form className="space-y-2 border-t border-neutral-200 pt-3" onSubmit={save}>
              <Field label="New message">
                <input className={inputClass} value={draft} maxLength={1024} required onChange={(e) => setDraft(e.target.value)} />
              </Field>
              <Button primary>Save configuration</Button>
            </form>
          </Card>
          <Card title="Rollout" subtitle="reported back by Data">
            <dl className="grid grid-cols-2 gap-y-2">
              <dt className="text-neutral-500">Status</dt>
              <dd><Badge tone={statusTone(c.data_config.status)}>{c.data_config.status}</Badge></dd>
              <dt className="text-neutral-500">Applied version</dt>
              <dd>{c.data_config.last_applied_version ? `v${c.data_config.last_applied_version}` : "-"}</dd>
              <dt className="text-neutral-500">In sync</dt>
              <dd><Badge tone={inSync ? "green" : "yellow"}>{inSync ? "yes" : "rolling out"}</Badge></dd>
            </dl>
            <p className="text-xs text-neutral-500">Control only reports whether the ConfigMap was applied, not downstream health.</p>
          </Card>
          <Card title="History">
            <Timeline events={c.timeline} />
          </Card>
        </div>
      )}
    </>
  );
}
