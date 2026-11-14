export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly issues: { loc: (string | number)[]; msg: string }[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  const timeout = AbortSignal.timeout(15000);
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      credentials: "same-origin",
      signal: options.signal
        ? AbortSignal.any([options.signal, timeout])
        : timeout,
      headers: { Accept: "application/json", ...options.headers },
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    if (timeout.aborted)
      throw new Error(
        "The server took too long to respond. Refresh to check the result before trying again.",
        { cause: error },
      );
    throw new Error(
      "Could not reach the server. Check your connection and try again.",
      { cause: error },
    );
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const issues = Array.isArray(body?.detail)
      ? body.detail.filter(
          (issue: { loc?: unknown; msg?: unknown }) =>
            Array.isArray(issue?.loc) && typeof issue?.msg === "string",
        )
      : [];
    throw new ApiError(
      response.status,
      typeof body?.detail === "string"
        ? body.detail
        : issues.length
          ? issues.map((issue: { msg: string }) => issue.msg).join(" ")
          : `Request failed (HTTP ${response.status}). Refresh and try again.`,
      issues,
    );
  }
  if (response.status === 204) return undefined as T;
  try {
    return await response.json();
  } catch (error) {
    throw new Error(
      "The server returned an unreadable response. Refresh to check the result before trying again.",
      { cause: error },
    );
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}

export interface ModeratorSession {
  timezone?: string | null;
  user_id?: string;
  organization?: { id: string; name: string } | null;
  organization_role?: "user" | "editor" | "admin" | null;
  needs_setup?: boolean;
  destination?: string;
  can_populate_test_users?: boolean;
  username: string;
  csrf: string;
}

export interface SignupWarningSettings {
  post_warning_message?: boolean;
  warning_hours_before_close?: number;
  warning_message?: string;
}

export interface EventRecord extends SignupWarningSettings {
  id: string;
  title: string;
  description?: string;
  location?: string;
  starts_at: number;
  duration_hours: number;
  tables: { name: string; capacity: number }[];
  status: string;
  closes_at: number | null;
  published_at?: number | null;
  series_id?: string | null;
  scheduled_publish_at?: number | null;
  archived_at?: number | null;
  signup_deleted_at?: number | null;
  close_error?: string | null;
  pairing_warnings?: string[];
  is_test?: boolean;
  test_generation?: string | null;
  test_user_count?: number;
  discord_url: string | null;
  discord_cleanup_remaining?: number;
  discord_cleanup_error?: string | null;
}

export interface EventTemplateRecord extends SignupWarningSettings {
  id: string;
  title: string;
  description?: string;
  location?: string;
  duration_hours: number;
  tables: { name: string; capacity: number }[];
}

export function mutationOptions(csrf: string, body?: unknown): RequestInit {
  return {
    method: "POST",
    headers: {
      "X-CSRF-Token": csrf,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  };
}
