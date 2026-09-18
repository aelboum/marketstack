// Placeholder landing page (docs/ROADMAP.md Phase 1.6). The login link
// points at the backend's own /auth/login -- the installed saas-os
// package's api.platform.build_platform_app() mounts the full OIDC
// redirect/callback/session-cookie flow server-side (api/auth/routes.py
// in saas-os); this frontend never implements auth logic of its own.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function HomePage() {
  return (
    <main>
      <h1>Product</h1>
      <p>Phase 1 scaffold -- no product functionality yet.</p>
      <a href={`${API_BASE_URL}/auth/login`}>Log in</a>
    </main>
  );
}
