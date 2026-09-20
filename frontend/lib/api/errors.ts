// Error shape shared by every route this product's backend mounts --
// both this product's own routers (product/*/routes.py) and the
// saas-os-provided /auth/* routes build on the same FastAPI
// HTTPException convention: `{"detail": "<message>"}` for a plain error,
// or FastAPI's own `{"detail": [{"loc": [...], "msg": "...", "type":
// "..."}]}` shape for a 422 request-validation failure
// (api.errors.unauthorized/not_found/forbidden/rate_limited in the
// installed saas-os package all return the plain-string form).
//
// Important, non-obvious backend behavior this client is written against
// (see product/agency/routes.py, product/crm/routes.py,
// product/marketing/routes.py's own module docstrings): every one of
// this product's own tenant-scoped routes deliberately collapses "this
// resource does not exist" and "it exists but you may not access it"
// into the *same* non-enumerating 404 -- never a 403 -- specifically so
// a caller cannot distinguish the two. A literal 403 can still occur
// (it is saas-os core's own `api.errors.forbidden()`, used by the
// platform's RBAC chokepoint outside this product's own routers), so
// this client treats 403 and a 404 returned for an authenticated,
// tenant-scoped request the same way in the UI: a permission-denied /
// not-accessible state, never a claim about which one it technically
// was. See docs/ROADMAP.md's UI Track / ARCHITECTURE.md §6.1 -- the
// frontend never re-derives an authorization decision, it only reflects
// what the backend already decided.
export type ApiErrorKind =
  | "unauthorized" // 401 -- no/expired session
  | "forbidden" // 403 or a tenant-scoped 404 -- treated as permission-denied
  | "not_found" // 404 on a request with no tenant-scoping ambiguity
  | "validation" // 400 or 422 -- client input error
  | "rate_limited" // 429
  | "server" // 5xx
  | "network"; // fetch itself failed (offline, DNS, CORS rejection, ...)

export interface ApiValidationDetail {
  loc: Array<string | number>;
  msg: string;
  type: string;
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly detail: string | ApiValidationDetail[] | null;
  readonly retryAfterSeconds: number | null;

  constructor(
    kind: ApiErrorKind,
    message: string,
    options: {
      status?: number | null;
      detail?: string | ApiValidationDetail[] | null;
      retryAfterSeconds?: number | null;
    } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status ?? null;
    this.detail = options.detail ?? null;
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
  }
}

/** Maps an HTTP status + parsed body to the ApiErrorKind taxonomy above. */
export function classifyErrorStatus(status: number): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403 || status === 404) return "forbidden";
  if (status === 400 || status === 422) return "validation";
  if (status === 429) return "rate_limited";
  if (status >= 500) return "server";
  return "server";
}
