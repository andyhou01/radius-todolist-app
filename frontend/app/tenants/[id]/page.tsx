"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, Json, PageHeader, statusTone } from "../../components/ui";
import { OpResult, errorText, plane, rememberTenant } from "../../lib/client";
import { Timeline, type TimelineEvent } from "../../components/timeline";

type Mgmt = {
  pair_id: string; isolation: string; operation_id: string; provisioning_status: string; provisioning_stage: string;
  error_code: string | null; onboarding_status: string; control_record: { status: string; observed_revision: number | null }; timeline: TimelineEvent[];
};

export default function TenantDetail() {
  const { id } = useParams<{ id: string }>();
  const [mgmt, setMgmt] = useState<OpResult | null>(null);
  const [auto, setAuto] = useState(true);
  const m = mgmt?.ok ? (mgmt.json as Mgmt) : null;

  const load = useCallback(async () => setMgmt(await plane("management", "GET", `/tenants/${id}?limit=100`)), [id]);

  useEffect(() => {
    rememberTenant(id);
    const first = setTimeout(load, 0);
    const timer = auto ? setInterval(load, 5000) : undefined;
    return () => {
      clearTimeout(first);
      if (timer) clearInterval(timer);
    };
  }, [id, load, auto]);

  return (
    <>
      <PageHeader
        title={`Tenant ${id}`}
        description="Onboarding as seen by Management. Configuration and runtime belong to the tenant admin and end users."
        actions={
          <>
            <label className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> auto-refresh
            </label>
            <Button onClick={load}>Refresh</Button>
          </>
        }
      />
      {!mgmt ? (
        <p className="text-neutral-400">loading…</p>
      ) : !m ? (
        <p className="rounded-xl bg-white p-3 font-medium ring-1 ring-neutral-900">{errorText(mgmt)}</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Onboarding" subtitle={`operation ${m.operation_id}`}>
            <dl className="grid grid-cols-2 gap-y-2">
              <dt className="text-neutral-500">Provisioning</dt>
              <dd><Badge tone={statusTone(m.provisioning_status)}>{m.provisioning_status}</Badge> <span className="text-xs text-neutral-500">{m.provisioning_stage}</span></dd>
              <dt className="text-neutral-500">Onboarding</dt>
              <dd><Badge tone={statusTone(m.onboarding_status)}>{m.onboarding_status}</Badge></dd>
              <dt className="text-neutral-500">Control record</dt>
              <dd><Badge tone={statusTone(m.control_record?.status)}>{m.control_record?.status}</Badge></dd>
              <dt className="text-neutral-500">Isolation</dt>
              <dd>{m.isolation}</dd>
              <dt className="text-neutral-500">Cluster pair</dt>
              <dd>{m.pair_id}</dd>
              {m.error_code && (
                <>
                  <dt className="text-neutral-500">Error</dt>
                  <dd className="font-semibold">{m.error_code}</dd>
                </>
              )}
            </dl>
          </Card>
          <Card title="Timeline">
            <Timeline events={m.timeline} />
          </Card>
        </div>
      )}
      <details className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-neutral-200">
        <summary className="cursor-pointer">Raw Management response</summary>
        <div className="pt-2"><Json value={mgmt?.json ?? mgmt?.stderr} /></div>
      </details>
    </>
  );
}
