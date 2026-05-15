import { createClient } from "./supabase";

// Build-time inlined env var. Falls back to the deployed backend so the app
// keeps working even if NEXT_PUBLIC_API_URL isn't passed during the build
// (Vercel + Next.js 16 Turbopack has been flaky about inlining this).
// For local dev, set NEXT_PUBLIC_API_URL=http://localhost:8000 in .env.local.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://backend-nakel0s-projects.vercel.app";

async function getAuthHeaders(): Promise<Record<string, string>> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session?.access_token) {
    return {};
  }

  return {
    Authorization: `Bearer ${session.access_token}`,
  };
}

async function apiRequest<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const authHeaders = await getAuthHeaders();
  const url = `${API_BASE}${path}`;

  const response = await fetch(url, {
    // Force a fresh fetch every time. Without this, stale browser /
    // intermediate caches were keeping LatAm postings visible in the
    // inbox for ~minutes after the server-side country filter dropped
    // them. TanStack Query handles its own in-memory cache; we don't
    // want a SECOND layer (HTTP) hiding state changes.
    cache: "no-store",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders,
      ...options.headers,
    },
  });

  if (response.status === 401) {
    // Redirect to login on auth failure
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    // FastAPI returns either a string detail (most endpoints) or a structured
    // dict (e.g. /apply's no_direct_posting). Preserve both: stringify for
    // the message, but attach the original detail so callers can read
    // structured codes.
    const detailRaw = (error as { detail?: unknown }).detail;
    const message =
      typeof detailRaw === "string"
        ? detailRaw
        : detailRaw && typeof detailRaw === "object" && "message" in detailRaw
          ? String((detailRaw as { message: unknown }).message)
          : `API error: ${response.status}`;
    const err = new Error(message) as Error & { detail?: unknown; status?: number };
    err.detail = detailRaw;
    err.status = response.status;
    throw err;
  }

  // 204 No Content has no body — calling .json() on it rejects, which was
  // breaking the resume delete button (mutation never fired onSuccess so
  // the row never disappeared from the UI even though the backend deleted it).
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

export const api = {
  get: <T>(path: string) => apiRequest<T>(path),

  post: <T>(path: string, body?: unknown) =>
    apiRequest<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    }),

  put: <T>(path: string, body?: unknown) =>
    apiRequest<T>(path, {
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
    }),

  patch: <T>(path: string, body?: unknown) =>
    apiRequest<T>(path, {
      method: "PATCH",
      body: body ? JSON.stringify(body) : undefined,
    }),

  delete: <T>(path: string) => apiRequest<T>(path, { method: "DELETE" }),

  upload: async <T>(
    path: string,
    file: File,
    fields?: Record<string, string>,
    fieldName = "file",
  ) => {
    const authHeaders = await getAuthHeaders();
    const formData = new FormData();
    formData.append(fieldName, file);
    if (fields) {
      for (const [key, value] of Object.entries(fields)) {
        formData.append(key, value);
      }
    }

    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: authHeaders,
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      const detailRaw = (error as { detail?: unknown }).detail;
      const message =
        typeof detailRaw === "string"
          ? detailRaw
          : detailRaw && typeof detailRaw === "object" && "message" in detailRaw
            ? String((detailRaw as { message: unknown }).message)
            : `Upload error: ${response.status}`;
      const err = new Error(message) as Error & { detail?: unknown; status?: number };
      err.detail = detailRaw;
      err.status = response.status;
      throw err;
    }

    return response.json() as Promise<T>;
  },
};
