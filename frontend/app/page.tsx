"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, PageHeader } from "./components/ui";
import { PLANES, knownTenants, plane } from "./lib/client";

type Health = Record<string, { state: "checking" | "healthy" | "down"; detail: string }>;

const FLOW = [
  ["1", "Tenant request", "Operator calls Management POST /tenants"],
  ["2", "Provision", "Management allocates a cluster pair; Radius deploys control and data"],
  ["3", "Control", "Control polls Management and stores desired configuration"],
  ["4", "Data", "Data polls Control, applies ConfigMaps and renders agentgateway routes"],
  ["5", "Use", "Tenant calls Data API; chat goes through agentgateway policies"],
];

export default function Overview() {
  const [health, setHealth] = useState<Health>({});
  const [tenantCount, setTenantCount] = useState(0);

  const check = useCallback(async () => {
    setHealth(Object.fromEntries(PLANES.map((p) => [p.target, { state: "checking", detail: "" }])));
    await Promise.all(
      PLANES.map(async (p) => {
        const result = await plane(p.target, "GET", "/healthz");
        const detail = result.ok ? "GET /healthz 200" : result.stderr.split("\n").filter(Boolean).pop() ?? "unreachable";
        setHealth((prev) => ({ ...prev, [p.target]: { state: result.ok ? "healthy" : "down", detail } }));
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

  return (
    <>
      <PageHeader
        title="Overview"
        description="Three application planes provisioned by Radius, with agentgateway in every data plane."
        actions={<Button onClick={check}>Refresh</Button>}
      />

      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Planes healthy">
          <div className="text-2xl font-semibold">
            {healthy} / {PLANES.length}
          </div>
        </Card>
        <Card title="Tenants tracked in this console">
          <div className="text-2xl font-semibold">{tenantCount}</div>
          <Link className="text-blue-700 underline" href="/tenants">
            Manage tenants
          </Link>
        </Card>
        <Card title="Next step">
          <p>{healthy === 0 ? "Environment not running. Start it from Operations." : "Create a tenant, then open it."}</p>
          <Link className="text-blue-700 underline" href={healthy === 0 ? "/operations" : "/tenants"}>
            {healthy === 0 ? "Go to Operations" : "Go to Tenants"}
          </Link>
        </Card>
      </div>

      <Card title="Planes">
        <table className="w-full">
          <thead>
            <tr className="border-b text-left text-gray-500">
              <th className="py-1">Plane</th>
              <th>Responsibility</th>
              <th>Status</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {PLANES.map((p) => {
              const h = health[p.target];
              return (
                <tr key={p.target} className="border-b last:border-0">
                  <td className="py-2 font-medium">{p.name}</td>
                  <td className="text-gray-600">{p.role}</td>
                  <td>
                    <Badge tone={h?.state === "healthy" ? "green" : h?.state === "down" ? "red" : "yellow"}>{h?.state ?? "checking"}</Badge>
                  </td>
                  <td className="text-xs text-gray-500">{h?.detail}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="text-xs text-gray-500">Isolated pairs exist only after an isolated tenant is provisioned, so they may show as down.</p>
      </Card>

      <Card title="How a tenant flows through the system">
        <ol className="grid gap-2 md:grid-cols-5">
          {FLOW.map(([n, title, text]) => (
            <li key={n} className="rounded border p-2">
              <div className="text-xs text-gray-500">Step {n}</div>
              <div className="font-medium">{title}</div>
              <div className="text-gray-600">{text}</div>
            </li>
          ))}
        </ol>
      </Card>
    </>
  );
}
