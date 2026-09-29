"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { PERSONAS, PERSONA_KEYS, knownTenants, personaForPath, rememberTenant, type PersonaKey } from "../lib/client";

type Session = { persona: PersonaKey; setPersona: (p: PersonaKey) => void; tenant: string; setTenant: (t: string) => void };

const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside Shell");
  return session;
}

const INITIALS: Record<PersonaKey, string> = { platform: "PA", "tenant-admin": "TA", "end-user": "EU" };

function PersonaSwitcher() {
  const { persona, setPersona } = useSession();
  const router = useRouter();
  return (
    <div className="space-y-1" role="radiogroup" aria-label="Acting as">
      {PERSONA_KEYS.map((key) => {
        const active = persona === key;
        return (
          <button
            key={key}
            role="radio"
            aria-checked={active}
            onClick={() => {
              setPersona(key);
              router.push(PERSONAS[key].home);
            }}
            className={`flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition ${active ? "bg-white shadow-sm ring-1 ring-neutral-200" : "hover:bg-neutral-200/50"}`}
          >
            <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-[11px] font-semibold ${active ? "bg-neutral-900 text-white" : "bg-neutral-200 text-neutral-600"}`}>
              {INITIALS[key]}
            </span>
            <span className="min-w-0">
              <span className={`block font-medium ${active ? "text-neutral-900" : "text-neutral-600"}`}>{PERSONAS[key].who}</span>
              <span className="block text-xs text-neutral-400">{PERSONAS[key].plane}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function TenantPicker() {
  const { tenant, setTenant } = useSession();
  const [known, setKnown] = useState<string[]>([]);
  const [typing, setTyping] = useState(false);
  const [draft, setDraft] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setKnown(knownTenants()), 0);
    return () => clearTimeout(timer);
  }, [tenant]);

  if (typing || known.length === 0) {
    return (
      <form
        className="flex flex-col gap-1.5 text-xs"
        onSubmit={(e) => {
          e.preventDefault();
          if (!draft) return;
          setTenant(draft);
          setDraft("");
          setTyping(false);
        }}
      >
        <input autoFocus className={`${inputClass} w-full text-xs`} placeholder="tenant id" value={draft} onChange={(e) => setDraft(e.target.value.trim())} />
        <div className="flex gap-1.5">
          <Button primary className="flex-1 text-xs" disabled={!draft}>Switch</Button>
          {known.length > 0 && (
            <Button type="button" className="text-xs" onClick={() => setTyping(false)}>Cancel</Button>
          )}
        </div>
      </form>
    );
  }

  return (
    <label className="relative flex items-center text-xs">
      <span className="sr-only">Tenant</span>
      <select
        className="w-full appearance-none rounded-lg bg-white py-2 pl-3 pr-8 font-medium ring-1 ring-neutral-200 transition hover:ring-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-900"
        value={tenant}
        onChange={(e) => (e.target.value === "__other" ? setTyping(true) : setTenant(e.target.value))}
      >
        {!known.includes(tenant) && <option value={tenant}>{tenant || "Select tenant"}</option>}
        {known.map((t) => <option key={t} value={t}>{t}</option>)}
        <option value="__other">Other tenant…</option>
      </select>
      <span aria-hidden className="pointer-events-none absolute right-3 text-[10px] text-neutral-500">▾</span>
    </label>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [savedPersona, setPersonaState] = useState<PersonaKey>("platform");
  const [tenant, setTenantState] = useState("");
  // Each page belongs to one persona, so the route decides who you are acting as.
  const persona = personaForPath(pathname) ?? savedPersona;

  useEffect(() => {
    const timer = setTimeout(() => {
      const saved = localStorage.getItem("demo.persona") as PersonaKey | null;
      if (saved && saved in PERSONAS) setPersonaState(saved);
      setTenantState(localStorage.getItem("demo.tenant") ?? knownTenants()[0] ?? "");
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  const session: Session = {
    persona,
    setPersona: (p) => {
      localStorage.setItem("demo.persona", p);
      setPersonaState(p);
    },
    tenant,
    setTenant: (t) => {
      localStorage.setItem("demo.tenant", t);
      rememberTenant(t);
      setTenantState(t);
    },
  };

  const current = PERSONAS[persona];

  return (
    <SessionContext.Provider value={session}>
      <div className="flex min-h-screen bg-neutral-50 text-sm text-neutral-900">
        <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col gap-6 border-r border-neutral-200 bg-neutral-100/60 p-4">
          <Link href={current.home} className="flex items-center gap-2.5 px-1 font-semibold tracking-tight">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-neutral-900 text-xs text-white">R</span>
            <span>
              Radius Planes
              <span className="block text-xs font-normal text-neutral-500">three-plane demo</span>
            </span>
          </Link>

          <div className="space-y-2">
            <div className="px-1 text-[11px] font-medium uppercase tracking-wider text-neutral-400">Acting as</div>
            <PersonaSwitcher />
          </div>

          {persona !== "platform" && (
            <div className="space-y-2">
              <div className="px-1 text-[11px] font-medium uppercase tracking-wider text-neutral-400">Tenant</div>
              <TenantPicker />
            </div>
          )}

          <nav className="space-y-1">
            <div className="px-1 pb-1 text-[11px] font-medium uppercase tracking-wider text-neutral-400">{current.plane}</div>
            {current.nav.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`block rounded-lg px-3 py-2 transition ${active ? "bg-neutral-900 font-medium text-white" : "text-neutral-600 hover:bg-neutral-200/60 hover:text-neutral-900"}`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <p className="mt-auto px-1 text-xs leading-relaxed text-neutral-400">{current.goal}</p>
        </aside>
        <main className="min-w-0 flex-1">
          <div className="mx-auto max-w-5xl space-y-8 px-10 py-10">{children}</div>
        </main>
      </div>
    </SessionContext.Provider>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="max-w-2xl text-neutral-500">{description}</p>}
      </div>
      <div className="flex items-center gap-2">{actions}</div>
    </div>
  );
}

export function Card({ title, subtitle, children, actions }: { title: string; subtitle?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-neutral-200">
      <div className="flex items-start justify-between gap-2 border-b border-neutral-100 px-5 py-4">
        <div>
          <h2 className="font-semibold">{title}</h2>
          {subtitle && <div className="text-xs text-neutral-500">{subtitle}</div>}
        </div>
        <div className="flex gap-2">{actions}</div>
      </div>
      <div className="space-y-3 p-5">{children}</div>
    </section>
  );
}

// Monochrome status: solid = good, outlined = bad, dashed = in progress, grey = unknown.
const TONE: Record<string, string> = {
  green: "bg-neutral-900 text-white border-neutral-900",
  red: "bg-white text-neutral-900 border-neutral-900 font-semibold",
  yellow: "bg-neutral-100 text-neutral-700 border-neutral-400 border-dashed",
  gray: "bg-neutral-50 text-neutral-400 border-neutral-200",
};
const MARK: Record<string, string> = { green: "●", red: "✕", yellow: "…", gray: "○" };

export function Badge({ tone = "gray", children }: { tone?: "green" | "red" | "yellow" | "gray"; children: ReactNode }) {
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs ${TONE[tone]}`}>
      <span aria-hidden className="text-[10px]">{MARK[tone]}</span>
      {children}
    </span>
  );
}

export function statusTone(value: unknown): "green" | "red" | "yellow" | "gray" {
  const v = String(value ?? "");
  if (["succeeded", "ready", "applied", "created", "ok", "healthy"].includes(v)) return "green";
  if (["failed", "interrupted", "down", "error"].includes(v)) return "red";
  if (["pending", "running", "accepted"].includes(v)) return "yellow";
  return "gray";
}

export function Button({ primary, className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { primary?: boolean }) {
  return (
    <button
      {...props}
      className={`rounded-lg px-3.5 py-1.5 font-medium shadow-sm transition disabled:opacity-40 ${primary ? "bg-neutral-900 text-white hover:bg-neutral-700" : "bg-white text-neutral-800 ring-1 ring-neutral-200 hover:bg-neutral-50"} ${className ?? ""}`}
    />
  );
}

export function Json({ value }: { value: unknown }) {
  return <pre className="max-h-72 overflow-auto rounded-xl bg-neutral-900 p-4 font-mono text-xs whitespace-pre-wrap text-neutral-100">{JSON.stringify(value, null, 2)}</pre>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-neutral-600">{label}</span>
      {children}
    </label>
  );
}

export function NeedTenant() {
  return <p className="rounded-2xl border border-dashed border-neutral-300 bg-white p-8 text-center text-neutral-500">Choose a tenant in the sidebar to sign in as that tenant.</p>;
}

export const inputClass = "rounded-lg bg-white px-3 py-1.5 ring-1 ring-neutral-200 transition focus:outline-none focus:ring-2 focus:ring-neutral-900";
