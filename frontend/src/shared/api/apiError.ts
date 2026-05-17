// API error type used across the frontend boundary.
//
// This is a separate module so that runtime parsers (`parse.ts`, `schemas.ts`)
// and the request layer (`client.ts`) can both reference it without forming
// a circular import.

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}
