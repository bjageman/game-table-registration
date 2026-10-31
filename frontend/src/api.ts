export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
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
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      credentials: "same-origin",
      headers: { Accept: "application/json", ...options.headers },
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new Error(
      "Could not reach the server. Check your connection and try again.",
      { cause: error },
    );
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      typeof body?.detail === "string"
        ? body.detail
        : "The request could not be completed. Please try again.",
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}

export interface ModeratorSession {
  username: string;
  csrf: string;
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
