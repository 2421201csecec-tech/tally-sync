export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch {
    throw new Error("Cannot reach the server. Please try again.");
  }
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? ((await response.json()) as { detail?: string } & T)
    : null;
  const text = data ? "" : await response.text();
  if (!response.ok) {
    if (data?.detail) throw new Error(data.detail);
    if (response.status >= 500) {
      throw new Error(text ? `Server error (${response.status}): ${text}` : `Server error (${response.status}).`);
    }
    throw new Error(`Request failed (${response.status}).`);
  }
  if (data) return data;
  throw new Error("The server returned an invalid response.");
}
