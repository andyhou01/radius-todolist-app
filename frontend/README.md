# Radius Planes console

Local web console for the three-plane demo. It calls the planes through the
repository's `make api` and `make kube` entrypoints, so start the local
environment first (see [RUN_LOCAL_SCENARIOS.md](../RUN_LOCAL_SCENARIOS.md)).

```bash
npm install
npm run dev   # http://localhost:35520
```

Choose who you act as in the sidebar:

| Persona | Plane | Pages |
|---|---|---|
| Platform admin | Management | Planes, Tenants, Operations |
| Tenant admin | Control | Configuration, Gateway policies |
| End user | Data | Application, AI Playground |

Check with `npx tsc --noEmit && npm run lint`.
