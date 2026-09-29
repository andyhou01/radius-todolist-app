"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, PageHeader } from "./components/ui";
import { PERSONAS, PERSONA_KEYS, PLANES, knownTenants, plane } from "./lib/client";

type Health = Record<string, { state: "checking" | "healthy" | "not provisioned" | "down"; detail: string }>;

export default function PlatformOverview() {
  const [health, setHealth] = useState<Health>({});
  const [tenantCount, setTenantCount] = useState(0);

  const check = useCallback(async () => {
    setHealth(Object.fromEntries(PLANES.map((p) => [p.target, { state: "checking", detail: "" }])));
    await Promise.all(
      PLANES.map(async (p) => {
        const result = await plane(p.target, "GET", "/healthz");
        const detail = result.ok ? "GET /healthz 200" : result.stderr.split("\n").filter(Boolean).pop() ?? "unreachable";
        // Local child clusters are created on demand by the first tenant of each pair.
        const missing = !result.ok && detail.includes("Expected one owned kind node");
        const state = result.ok ? "healthy" : missing ? "not provisioned" : "down";
        setHealth((prev) => ({ ...prev, [p.target]: { state, detail: missing ? "Created by the first tenant on this pair" : detail } }));
      }),
    );
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      setTenantCount(knownTenants().length);
      check();
    }, 0);
    return () => clearTimeout(timer);
  }, [check]);

  const healthy = Object.values(health).filter((h) => h.state === "healthy").length;
  const tone = (state?: string) => (state === "healthy" ? "green" : state === "down" ? "red" : state === "not provisioned" ? "gray" : "yellow");

  return (
    <>
      <PageHeader
        title="Planes"
        description="Every plane runs on its own cluster. Management creates the control and data clusters for each cluster pair through Radius."
        actions={<Button onClick={check}>Refresh</Button>}
      />

      <div className="grid gap-4 md:grid-cols-3">
        {[
          [`${healthy} / ${PLANES.length}`, "planes healthy"],
          [String(tenantCount), "tenants tracked"],
          [healthy === 0 ? "Start environment" : "Onboard tenant", healthy === 0 ? "/operations" : "/tenants"],
        ].map(([value, label], i) => (
          <div key={i} className={`rounded-2xl p-5 shadow-sm ring-1 ${i === 2 ? "bg-neutral-900 text-white ring-neutral-900" : "bg-white ring-neutral-200"}`}>
            {i < 2 ? (
              <>
                <div className="text-3xl font-semibold">{value}</div>
                <div className="text-xs text-neutral-500">{label}</div>
              </>
            ) : (
              <>
                <div className="text-xs text-neutral-400">Next step</div>
                <Link href={label} className="mt-2 inline-block text-lg font-medium hover:underline underline-offset-4">
                  {value} →
                </Link>
              </>
            )}
          </div>
        ))}
      </div>

      <Card title="Plane health" subtitle="Health is checked through each plane's own API.">
        <table className="w-full">
          <thead>
            <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
              <th className="py-2">Plane</th>
              <th>Cluster pair</th>
              <th>Used by</th>
              <th>Status</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {PLANES.map((p) => {
              const h = health[p.target];
              const persona = PERSONAS[PERSONA_KEYS.find((k) => PERSONAS[k].plane.startsWith(p.name)) ?? "platform"];
              return (
                <tr key={p.target} className="border-b border-neutral-200 last:border-0">
                  <td className="py-2 font-medium">{p.name}</td>
                  <td>{p.pair}</td>
                  <td className="text-neutral-600">{persona.who}</td>
                  <td><Badge tone={tone(h?.state)}>{h?.state ?? "checking"}</Badge></td>
                  <td className="max-w-xs truncate text-xs text-neutral-500" title={h?.detail}>{h?.detail || p.role}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>

      <Card title="Who uses which plane" subtitle="Switch persona in the sidebar to see each view.">
        <div className="grid gap-4 md:grid-cols-3">
          {PERSONA_KEYS.map((key) => (
            <div key={key} className="space-y-1 rounded-xl bg-neutral-50 p-4 ring-1 ring-neutral-100">
              <div className="font-semibold">{PERSONAS[key].who}</div>
              <div className="text-xs uppercase tracking-wide text-neutral-500">{PERSONAS[key].plane}</div>
              <p className="text-neutral-600">{PERSONAS[key].goal}</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-neutral-500">Children pull from parents: Control pulls tenants from Management, Data pulls configuration from Control.</p>
      </Card>
    </>
  );
}
