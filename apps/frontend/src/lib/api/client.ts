import { env } from "@/lib/env";

export class ApiError extends Error {
  status: number;
  code: string;
  details?: Record<string, unknown>;
  requestId?: string;

  constructor(opts: {
    status: number;
    message: string;
    code: string;
    details?: Record<string, unknown>;
    requestId?: string;
  }) {
    super(opts.message);
    this.status = opts.status;
    this.code = opts.code;
    this.details = opts.details;
    this.requestId = opts.requestId;
  }
}

type ApiInit = Omit<RequestInit, "body"> & {
  body?: BodyInit | object | null;
  baseUrl?: string;
  token?: string | null;
};

export async function api<T = unknown>(path: string, init: ApiInit = {}): Promise<T> {
  const base =
    init.baseUrl ?? (typeof window === "undefined" ? env.API_INTERNAL_BASE_URL : env.API_BASE_URL);
  const url = path.startsWith("http") ? path : `${base.replace(/\/$/, "")}${path}`;

  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData) && init.body !== undefined && init.body !== null) {
    if (!headers.has("Content-Type") && typeof init.body === "object") {
      headers.set("Content-Type", "application/json");
    }
  }
  headers.set("Accept", "application/json");
  if (init.token) headers.set("Authorization", `Bearer ${init.token}`);

  const body =
    init.body && typeof init.body === "object" && !(init.body instanceof FormData)
      ? JSON.stringify(init.body)
      : (init.body as BodyInit | undefined | null);

  const res = await fetch(url, {
    ...init,
    headers,
    body: body ?? undefined,
    credentials: init.credentials ?? "include",
    cache: init.cache ?? "no-store",
  });

  if (res.status === 204) {
    return undefined as T;
  }

  const ct = res.headers.get("content-type") ?? "";
  const isJson = ct.includes("application/json");
  const payload = isJson ? await res.json().catch(() => null) : await res.text();

  if (!res.ok) {
    type ErrorEnvelope = {
      error?: {
        message?: string;
        code?: string;
        details?: Record<string, unknown>;
        request_id?: string;
      };
    };
    const err = (payload && typeof payload === "object" ? (payload as ErrorEnvelope).error : null) ?? {};
    throw new ApiError({
      status: res.status,
      message: err.message ?? res.statusText ?? "Request failed",
      code: err.code ?? "http_error",
      details: err.details,
      requestId: err.request_id ?? res.headers.get("x-request-id") ?? undefined,
    });
  }

  return payload as T;
}
