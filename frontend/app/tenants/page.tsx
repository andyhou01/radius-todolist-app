"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, Field, PageHeader, inputClass, statusTone } from "../components/ui";
import { errorText, forgetTenant, knownTenants, plane, rememberTenant } from "../lib/client";

type Row = { id: string; loading: boolean; pair?: string; isolation?: string; provisioning?: string; stage?: string; onboarding?: string; error?: string };

export default function Tenants() {
  const router = useRouter();
  const [rows, setRows] = useState<Row[]>([]);
  const [form, setForm] = useState({ tenant_id: "shared-a", isolation: "shared", initial_message: "alpha" });
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const [lookup, setLookup] = useState("");

  const load = useCallback(async () => {
    const ids = knownTenants();
    setRows(ids.map((id) => ({ id, loading: true })));
    await Promise.all(
      ids.map(async (id) => {
        const result = await plane("management", "GET", `/tenants/${id}`);
        const t = result.json as Record<string, string> | null;
        const row: Row = result.ok && t
          ? { id, loading: false, pair: t.pair_id, isolation: t.isolation, provisioning: t.provisioning_status, stage: t.provisioning_stage, onboarding: t.onboarding_status }
          : { id, loading: false, error: errorText(result) };
        setRows((prev) => prev.map((r) => (r.id === id ? row : r)));
      }),
    );
  }, []);

  useEffect(() => {
    const timer = setTimeout(load, 0);
    return () => clearTimeout(timer);
  }, [load]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);
    const result = await plane("management", "POST", "/tenants", form);
    setSubmitting(false);
    if (result.ok) {
      rememberTenant(form.tenant_id);
      setMessage({ tone: "green", text: `Accepted. Operation ${(result.json as { operation_id?: string })?.operation_id ?? ""}` });
      load();
    } else {
      if (result.status === 409) rememberTenant(form.tenant_id);
      setMessage({ tone: "red", text: errorText(result) });
      load();
    }
  }

  return (
    <>
      <PageHeader title="Tenants" description="Onboard tenants and allocate cluster pairs. Tenant configuration and runtime belong to the tenant admin and end users." actions={<Button onClick={load}>Refresh</Button>} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Onboard a tenant" subtitle="Management POST /tenants">
          <form className="space-y-3" onSubmit={create}>
            <Field label="Tenant ID">
              <input className={inputClass} value={form.tenant_id} pattern="[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?" required onChange={(e) => setForm({ ...form, tenant_id: e.target.value })} />
            </Field>
            <Field label="Isolation">
              <select className={inputClass} value={form.isolation} onChange={(e) => setForm({ ...form, isolation: e.target.value })}>
                <option value="shared">shared (reuse shared cluster pair)</option>
                <option value="isolated">isolated (own cluster pair)</option>
              </select>
            </Field>
            <Field label="Initial message">
              <input className={inputClass} value={form.initial_message} maxLength={1024} required onChange={(e) => setForm({ ...form, initial_message: e.target.value })} />
            </Field>
            <Button primary disabled={submitting}>{submitting ? "Submitting…" : "Create tenant"}</Button>
            {message && <p className={message.tone === "green" ? "text-neutral-700" : "font-semibold"}>{message.text}</p>}
          </form>
        </Card>

        <div className="lg:col-span-2">
          <Card
            title="Tenants"
            actions={
              <form
                className="flex gap-1"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!lookup) return;
                  rememberTenant(lookup);
                  router.push(`/tenants/${lookup}`);
                }}
              >
                <input className={`${inputClass} text-xs`} placeholder="open existing tenant id" value={lookup} onChange={(e) => setLookup(e.target.value.trim())} />
                <Button className="text-xs">Open</Button>
              </form>
            }
          >
            {rows.length === 0 && <p className="text-neutral-500">No tenants yet. Create one, or open an existing tenant by ID.</p>}
            {rows.length > 0 && (
              <table className="w-full">
                <thead>
                  <tr className="border-b text-left text-neutral-500">
                    <th className="py-1">Tenant</th>
                    <th>Isolation</th>
                    <th>Cluster pair</th>
                    <th>Provisioning</th>
                    <th>Onboarding</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className="border-b last:border-0">
                      <td className="py-2">
                        <Link className="font-medium underline underline-offset-4" href={`/tenants/${r.id}`}>
                          {r.id}
                        </Link>
                      </td>
                      {r.loading ? (
                        <td colSpan={4} className="text-neutral-400">loading…</td>
                      ) : r.error ? (
                        <td colSpan={4} className="text-xs font-semibold">{r.error}</td>
                      ) : (
                        <>
                          <td>{r.isolation}</td>
                          <td>{r.pair ?? "-"}</td>
                          <td>
                            <Badge tone={statusTone(r.provisioning)}>{r.provisioning}</Badge> <span className="text-xs text-neutral-500">{r.stage}</span>
                          </td>
                          <td>
                            <Badge tone={statusTone(r.onboarding)}>{r.onboarding}</Badge>
                          </td>
                        </>
                      )}
                      <td className="text-right">
                        <button
                          className="text-xs text-neutral-500 underline"
                          onClick={() => {
                            forgetTenant(r.id);
                            load();
                          }}
                        >
                          hide
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="text-xs text-neutral-500">The Management API has no list endpoint; this console remembers tenants you create or open.</p>
          </Card>
        </div>
      </div>
    </>
  );
}
