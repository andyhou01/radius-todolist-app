"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useTenantPlane } from "../components/tenant";
import { Button, NeedTenant, PageHeader } from "../components/ui";
import { OpResult, errorText, plane } from "../lib/client";

type Data = { message: string; applied_version: number; counter: number };

export default function Application() {
  const { tenant, target, error } = useTenantPlane("data");
  const [result, setResult] = useState<OpResult | null>(null);
  const [notice, setNotice] = useState("");
  const d = result?.ok ? (result.json as Data) : null;

  const load = useCallback(async () => {
    if (target) setResult(await plane(target, "GET", `/tenants/${tenant}`));
  }, [target, tenant]);

  useEffect(() => {
    const timer = setTimeout(load, 0);
    return () => clearTimeout(timer);
  }, [load]);

  async function increment() {
    if (!target) return;
    const next = await plane(target, "POST", `/tenants/${tenant}/counter`);
    if (next.ok) setResult(next);
    setNotice(next.ok ? "" : errorText(next));
  }

  if (!tenant) return <NeedTenant />;

  return (
    <>
      <PageHeader title={`Welcome, ${tenant}`} description="Your tenant application, served by the data plane." actions={<Button onClick={load}>Refresh</Button>} />
      {(error || notice) && <p className="rounded-xl bg-white p-3 font-medium ring-1 ring-neutral-900">{error || notice}</p>}
      {!d ? (
        !error && <p className="text-neutral-400">{result ? errorText(result) : "loading…"}</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <section className="flex min-h-64 flex-col justify-between rounded-2xl bg-neutral-900 p-8 text-white shadow-sm lg:col-span-2">
            <div className="text-xs font-medium uppercase tracking-widest text-neutral-400">Message of the day</div>
            <p className="my-8 text-5xl font-semibold tracking-tight break-words">{d.message}</p>
            <div className="flex items-center gap-2 text-xs text-neutral-400">
              <span className="rounded-full bg-white/10 px-2.5 py-0.5 text-neutral-200">v{d.applied_version}</span>
              set by your tenant admin, applied from the local ConfigMap
            </div>
          </section>
          <section className="flex flex-col justify-between rounded-2xl bg-white p-8 shadow-sm ring-1 ring-neutral-200">
            <div className="text-xs font-medium uppercase tracking-widest text-neutral-500">Counter</div>
            <p className="my-6 font-mono text-7xl font-semibold tracking-tight tabular-nums">{d.counter}</p>
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-neutral-500">stored in tenant Redis</span>
              <Button primary onClick={increment}>Increment</Button>
            </div>
          </section>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-white px-5 py-4 text-neutral-600 shadow-sm ring-1 ring-neutral-200">
        <span>This page only calls the data plane, so it keeps working while Control is down.</span>
        <Link className="font-medium text-neutral-900 hover:underline underline-offset-4" href="/playground">
          Open AI Playground →
        </Link>
      </div>
    </>
  );
}
