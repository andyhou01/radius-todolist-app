"use client";

import { useState } from "react";
import { Badge, Button, Card, PageHeader } from "../components/ui";

type OpResult = { ok: boolean; stdout: string; stderr: string };

const STEPS = [
  ["make init ENV=local", "Write the local .env (once)"],
  ["make build CONFIRM_LOCAL=yes", "Build images and pull pinned dependencies"],
  ["make bootstrap CONFIRM_LOCAL=yes", "Create the management kind cluster and install Radius"],
  ["make deploy-management CONFIRM_LOCAL=yes", "Deploy the management plane application"],
  ["(this console) Tenants → Create", "Management provisions child clusters and deploys control + data"],
];

export default function Operations() {
  const [output, setOutput] = useState<{ kind: string; result: OpResult } | null>(null);
  const [busy, setBusy] = useState("");

  async function run(kind: "endpoints" | "report") {
    setBusy(kind);
    const response = await fetch(`/api/ops?kind=${kind}`);
    setOutput({ kind, result: await response.json() });
    setBusy("");
  }

  return (
    <>
      <PageHeader title="Operations" description="Environment lifecycle. Long-running steps run in a terminal from the repository root." />
      <Card title="Bring up the local environment">
        <ol className="space-y-2">
          {STEPS.map(([command, text], index) => (
            <li key={command} className="flex gap-3">
              <span className="text-gray-400">{index + 1}.</span>
              <div>
                <code className="rounded bg-gray-100 px-1">{command}</code>
                <div className="text-gray-600">{text}</div>
              </div>
            </li>
          ))}
        </ol>
      </Card>
      <Card
        title="Inspect"
        actions={
          <>
            <Button disabled={!!busy} onClick={() => run("endpoints")}>{busy === "endpoints" ? "Running…" : "make endpoints"}</Button>
            <Button disabled={!!busy} onClick={() => run("report")}>{busy === "report" ? "Running…" : "make report"}</Button>
          </>
        }
      >
        {!output && <p className="text-gray-500">Run a command to see current endpoints and plane state.</p>}
        {output && (
          <>
            <Badge tone={output.result.ok ? "green" : "red"}>{output.result.ok ? "ok" : "failed"}</Badge>
            <pre className="max-h-96 overflow-auto rounded bg-gray-50 p-2 text-xs whitespace-pre-wrap">
              {[output.result.stdout, output.result.stderr].filter(Boolean).join("\n")}
            </pre>
          </>
        )}
      </Card>
    </>
  );
}
