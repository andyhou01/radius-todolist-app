"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, Field, Json, PageHeader, inputClass, statusTone } from "../../components/ui";
import { OpResult, errorText, pairTargets, plane, rememberTenant } from "../../lib/client";

type Event = { event_id: number; type: string; stage?: string | null; version?: number | null; error_code?: string | null; received_at: string };
type Mgmt = {
  pair_id: string; isolation: string; operation_id: string; provisioning_status: string; provisioning_stage: string;
  error_code: string | null; onboarding_status: string; control_record: { status: string; observed_revision: number | null }; timeline: Event[];
};
type Ctrl = { desired: { message: string; version: number }; data_config: { status: string; last_applied_version: number | null }; timeline: Event[] };
type Data = { message: string; applied_version: number; counter: number };

function Timeline({ events }: { events: Event[] }) {
  if (!events?.length) return <p className="text-gray-500">No events yet.</p>;
  return (
    <ul className="max-h-60 overflow-auto text-xs">
      {[...events].reverse().map((e) => (
        <li key={e.event_id} className="border-b py-1 last:border-0">
          <span className="text-gray-500">{new Date(e.received_at).toLocaleTimeString()}</span> <b>{e.type}</b>
          {e.stage ? ` · ${e.stage}` : ""}
          {e.version ? ` · v${e.version}` : ""}
          {e.error_code ? <span className="text-red-600"> · {e.error_code}</span> : ""}
        </li>
      ))}
    </ul>
  );
}

function Unavailable({ result }: { result: OpResult | null }) {
  if (!result) return <p className="text-gray-400">loading…</p>;
  return <p className="text-red-600 text-xs">{errorText(result)}</p>;
}

export default function TenantDetail() {
  const { id } = useParams<{ id: string }>();
  const [mgmt, setMgmt] = useState<OpResult | null>(null);
  const [ctrl, setCtrl] = useState<OpResult | null>(null);
  const [data, setData] = useState<OpResult | null>(null);
  const [newMessage, setNewMessage] = useState("");
  const [notice, setNotice] = useState("");
  const [auto, setAuto] = useState(true);

  const m = mgmt?.ok ? (mgmt.json as Mgmt) : null;
  const c = ctrl?.ok ? (ctrl.json as Ctrl) : null;
  const d = data?.ok ? (data.json as Data) : null;

  const load = useCallback(async () => {
    const management = await plane("management", "GET", `/tenants/${id}?limit=100`);
    setMgmt(management);
    const pair = (management.json as Mgmt | null)?.pair_id;
    if (!management.ok || !pair) return;
    const targets = pairTargets(pair);
    const [control, dataPlane] = await Promise.all([
      plane(targets.control, "GET", `/tenants/${id}?limit=100`),
      plane(targets.data, "GET", `/tenants/${id}`),
    ]);
    setCtrl(control);
    setData(dataPlane);
  }, [id]);

  useEffect(() => {
    rememberTenant(id);
    const first = setTimeout(load, 0);
    const timer = auto ? setInterval(load, 5000) : undefined;
    return () => {
      clearTimeout(first);
      if (timer) clearInterval(timer);
    };
  }, [id, load, auto]);

  async function updateConfig(event: React.FormEvent) {
    event.preventDefault();
    if (!m) return;
    const result = await plane(pairTargets(m.pair_id).control, "PUT", `/tenants/${id}/configuration`, { message: newMessage });
    setNotice(result.ok ? `Control stored version ${(result.json as Ctrl)?.desired?.version}. Data applies it on its next poll.` : errorText(result));
    load();
  }

  async function increment() {
    if (!m) return;
    const result = await plane(pairTargets(m.pair_id).data, "POST", `/tenants/${id}/counter`);
    setNotice(result.ok ? "Counter incremented in the tenant's Redis." : errorText(result));
    setData(result.ok ? result : data);
  }

  return (
    <>
      <PageHeader
        title={`Tenant ${id}`}
        description={m ? `${m.isolation} tenant on cluster pair "${m.pair_id}"` : "Management → Control → Data"}
        actions={
          <>
            <label className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> auto-refresh 5s
            </label>
            <Button onClick={load}>Refresh</Button>
            <Link href={`/playground?tenant=${id}`} className="rounded border bg-white px-3 py-1 hover:bg-gray-50">
              Open in AI Playground
            </Link>
          </>
        }
      />
      {notice && <p className="rounded border bg-yellow-50 px-3 py-2">{notice}</p>}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="1 · Management plane">
          {!m ? (
            <Unavailable result={mgmt} />
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-1">
                <dt className="text-gray-500">Provisioning</dt>
                <dd><Badge tone={statusTone(m.provisioning_status)}>{m.provisioning_status}</Badge></dd>
                <dt className="text-gray-500">Stage</dt>
                <dd>{m.provisioning_stage}</dd>
                <dt className="text-gray-500">Onboarding</dt>
                <dd><Badge tone={statusTone(m.onboarding_status)}>{m.onboarding_status}</Badge></dd>
                <dt className="text-gray-500">Control record</dt>
                <dd><Badge tone={statusTone(m.control_record?.status)}>{m.control_record?.status}</Badge></dd>
                <dt className="text-gray-500">Cluster pair</dt>
                <dd>{m.pair_id}</dd>
                {m.error_code && (
                  <>
                    <dt className="text-gray-500">Error</dt>
                    <dd className="text-red-600">{m.error_code}</dd>
                  </>
                )}
              </dl>
              <h3 className="pt-2 font-medium">Timeline</h3>
              <Timeline events={m.timeline} />
            </>
          )}
        </Card>

        <Card title="2 · Control plane">
          {!m ? (
            <p className="text-gray-400">Waiting for Management.</p>
          ) : !c ? (
            <Unavailable result={ctrl} />
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-1">
                <dt className="text-gray-500">Desired message</dt>
                <dd>{c.desired.message}</dd>
                <dt className="text-gray-500">Desired version</dt>
                <dd>v{c.desired.version}</dd>
                <dt className="text-gray-500">Data apply</dt>
                <dd><Badge tone={statusTone(c.data_config.status)}>{c.data_config.status}</Badge></dd>
                <dt className="text-gray-500">Applied version</dt>
                <dd>{c.data_config.last_applied_version ? `v${c.data_config.last_applied_version}` : "-"}</dd>
              </dl>
              <form className="flex items-end gap-2 pt-2" onSubmit={updateConfig}>
                <Field label="Change message">
                  <input className={inputClass} value={newMessage} maxLength={1024} required onChange={(e) => setNewMessage(e.target.value)} />
                </Field>
                <Button>Update</Button>
              </form>
              <h3 className="pt-2 font-medium">Timeline</h3>
              <Timeline events={c.timeline} />
            </>
          )}
        </Card>

        <Card title="3 · Data plane">
          {!m ? (
            <p className="text-gray-400">Waiting for Management.</p>
          ) : !d ? (
            <Unavailable result={data} />
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-1">
                <dt className="text-gray-500">Served message</dt>
                <dd>{d.message}</dd>
                <dt className="text-gray-500">Applied version</dt>
                <dd>v{d.applied_version}</dd>
                <dt className="text-gray-500">Counter (Redis)</dt>
                <dd>{d.counter}</dd>
              </dl>
              <Button onClick={increment}>Increment counter</Button>
              <p className="text-xs text-gray-500">Data serves only its local ConfigMap and Redis; it keeps serving if Control is down.</p>
            </>
          )}
        </Card>
      </div>

      <details className="rounded border p-3">
        <summary className="cursor-pointer">Raw API responses</summary>
        <div className="grid gap-2 pt-2 lg:grid-cols-3">
          <Json value={mgmt?.json ?? mgmt?.stderr} />
          <Json value={ctrl?.json ?? ctrl?.stderr} />
          <Json value={data?.json ?? data?.stderr} />
        </div>
      </details>
    </>
  );
}
