// Single source of the Product backend's base URL. Every other module in
// this codebase that needs to reach the backend (the API client, the
// login link, anything else) imports from here -- never reads
// `process.env.NEXT_PUBLIC_API_URL` directly, so there is exactly one
// place this default/override lives (UI-1 requirement: no duplicated API
// URL construction).
//
// NEXT_PUBLIC_* is inlined into the client bundle at build time (Next.js
// convention) -- this is a base URL, never a secret.
export const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
