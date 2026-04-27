import { createClient } from "./supabase";

// Build-time inlined env var. Falls back to the deployed backend so the app
// keeps working even if NEXT_PUBLIC_API_URL isn't passed during the build
// (Vercel + Next.js 16 Turbopack has been flaky about inlining this).
// For local dev, set NEXT_PUBLIC_API_URL=http://localhost:8000 in .env.local.
const API_BASE =
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
    throw new Error(error.detail || `API error: ${response.status}`);
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
      throw new Error(error.detail || `Upload error: ${response.status}`);
    }

    return response.json() as Promise<T>;
  },
};
