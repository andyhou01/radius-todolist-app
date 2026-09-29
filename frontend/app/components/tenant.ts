"use client";

import { useEffect, useState } from "react";
import { pairTargets, resolvePair } from "../lib/client";
import { useSession } from "./ui";

// Resolves the signed-in tenant's control or data plane target.
export function useTenantPlane(kind: "control" | "data") {
  const { tenant } = useSession();
  const [state, setState] = useState<{ tenant: string; target: string | null; error: string }>({ tenant: "", target: null, error: "" });

  useEffect(() => {
    let cancelled = false;
    if (!tenant) return;
    resolvePair(tenant).then(({ pair, error }) => {
      if (!cancelled) setState({ tenant, target: pair ? pairTargets(pair)[kind] : null, error });
    });
    return () => {
      cancelled = true;
    };
  }, [tenant, kind]);

  return tenant && state.tenant === tenant ? state : { tenant, target: null, error: "" };
}
