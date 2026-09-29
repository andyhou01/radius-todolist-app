"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/tenants", label: "Tenants" },
  { href: "/playground", label: "AI Playground" },
  { href: "/gateway", label: "Gateway policies" },
  { href: "/operations", label: "Operations" },
];

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="flex min-h-screen text-sm">
      <aside className="w-52 shrink-0 border-r bg-gray-50 p-4">
        <div className="mb-6">
          <div className="font-semibold">Radius Planes</div>
          <div className="text-xs text-gray-500">local demo console</div>
        </div>
        <nav className="flex flex-col gap-1">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link key={item.href} href={item.href} className={`rounded px-2 py-1 ${active ? "bg-gray-200 font-medium" : "hover:bg-gray-100"}`}>
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <main className="flex-1 p-6 space-y-6 max-w-6xl">{children}</main>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b pb-3">
      <div>
        <h1 className="text-lg font-semibold">{title}</h1>
        {description && <p className="text-gray-500">{description}</p>}
      </div>
      <div className="flex gap-2">{actions}</div>
    </div>
  );
}

export function Card({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="border rounded bg-white">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <h2 className="font-medium">{title}</h2>
        <div className="flex gap-2">{actions}</div>
      </div>
      <div className="p-3 space-y-2">{children}</div>
    </section>
  );
}

const TONE: Record<string, string> = {
  green: "bg-green-100 text-green-800",
  red: "bg-red-100 text-red-800",
  yellow: "bg-yellow-100 text-yellow-800",
  gray: "bg-gray-100 text-gray-700",
};

export function Badge({ tone = "gray", children }: { tone?: "green" | "red" | "yellow" | "gray"; children: ReactNode }) {
  return <span className={`inline-block rounded px-2 py-0.5 text-xs ${TONE[tone]}`}>{children}</span>;
}

export function statusTone(value: unknown): "green" | "red" | "yellow" | "gray" {
  const v = String(value ?? "");
  if (["succeeded", "ready", "applied", "created", "ok", "healthy"].includes(v)) return "green";
  if (["failed", "interrupted", "down", "error"].includes(v)) return "red";
  if (["pending", "running", "accepted"].includes(v)) return "yellow";
  return "gray";
}

export function Button(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...props} className={`rounded border bg-white px-3 py-1 hover:bg-gray-50 disabled:opacity-50 ${props.className ?? ""}`} />;
}

export function Json({ value }: { value: unknown }) {
  return <pre className="max-h-72 overflow-auto rounded bg-gray-50 p-2 text-xs whitespace-pre-wrap">{JSON.stringify(value, null, 2)}</pre>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-gray-600">{label}</span>
      {children}
    </label>
  );
}

export const inputClass = "rounded border px-2 py-1";
