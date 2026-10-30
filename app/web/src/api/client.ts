// API client. Same error contract as the legacy api.js:
//   ApiError { kind: "http" | "network", status, code, message, version? }
// Client-only codes (not in the server's ErrorBody): "network" (API unreachable),
// "bad_response" (2xx without valid JSON), "http_<status>" (error without ErrorBody) and
// "unauthenticated" with status 401 when the Access session expired and the server answers
// with a redirect (calls use redirect: "manual"; the opaque redirect becomes this error).
// No statement data or file names go in URLs.

export type ApiErrorKind = "http" | "network";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;
  readonly code: string;
  readonly version?: number;

  constructor(kind: ApiErrorKind, status: number, code: string, message: string, version?: number) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.code = code;
    if (version !== undefined) this.version = version;
  }
}

async function toError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  const e = (body as { error?: { code?: unknown; message?: unknown; version?: unknown } } | null)
    ?.error;
  const code = typeof e?.code === "string" ? e.code : `http_${res.status}`;
  const message = typeof e?.message === "string" ? e.message : `Erro ${res.status}`;
  // 409 conflict carries the current version in error.version.
  const version = typeof e?.version === "number" ? e.version : undefined;
  return new ApiError("http", res.status, code, message, version);
}

export async function send(url: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(url, { redirect: "manual", ...init });
  } catch {
    throw new ApiError("network", 0, "network", "Sem conexão com o servidor");
  }
  if (res.type === "opaqueredirect") {
    throw new ApiError("http", 401, "unauthenticated", "Sessão expirada. Entre novamente");
  }
  if (!res.ok) throw await toError(res);
  return res;
}

export async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await send(url, init);
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError("http", res.status, "bad_response", "Resposta inválida do servidor");
  }
}
