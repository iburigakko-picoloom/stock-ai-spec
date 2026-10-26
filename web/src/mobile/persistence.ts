// Audited operations-only writes. Unknown routes keep the full durable save.
export function operationsOnly(method?: string, path = ""): boolean {
  return method === "POST" && (
    ["/api/v1/mobile/portfolio", "/api/v1/mobile/personal/settings",
      "/api/v1/mobile/personal/initial/preview", "/api/v1/mobile/personal/initial/confirm",
      "/api/v1/mobile/personal/current/preview", "/api/v1/mobile/personal/current/confirm",
      "/api/v1/executions/manual", "/api/v1/portfolio/apply-executions", "/api/v1/imports/executions/preview",
      "/api/v1/imports/positions/preview"].includes(path)
    || /^\/api\/v1\/stocks\/[A-Z0-9]{1,10}\/note$/.test(path)
    || /^\/api\/v1\/proposals\/[^/?#]+\/decisions$/.test(path)
    || /^\/api\/v1\/decisions\/[^/?#]+\/executions$/.test(path)
    || /^\/api\/v1\/imports\/(executions|positions)\/[^/?#]+\/confirm$/.test(path)
  );
}

export function requiresPersistence(method?: string, path = ""): boolean {
  // Review only validates/recalculates; it writes neither database.
  return method === "POST" && !/^\/api\/v1\/proposals\/[^/?#]+\/review$/.test(path);
}
