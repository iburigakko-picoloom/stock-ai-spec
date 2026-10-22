export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly detail: string;

  constructor(status: number, detail: string, code: string | null = null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export function responseError(status: number, body: unknown): ApiError {
  const value = body as { detail?: unknown; code?: unknown } | null;
  return new ApiError(status,
    typeof value?.detail === "string" ? value.detail : `API error ${status}`,
    typeof value?.code === "string" ? value.code : null);
}
