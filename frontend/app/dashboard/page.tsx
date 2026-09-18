"use client";

import { useEffect, useState } from "react";

// The authenticated placeholder page docs/ROADMAP.md Phase 1.6 calls for.
// Calls the backend's GET /auth/me (saas-os's own session-check endpoint,
// api/auth/routes.py) with credentials included so the session cookie
// /auth/callback set is sent; a 401 means there is no valid session, so
// this redirects to the login page rather than rendering anything.
//
// NOT yet verified end-to-end against a real ZITADEL instance -- see
// docs/RISKS-AND-OPEN-QUESTIONS.md. This page's own logic (call /auth/me,
// render the user id, log out) is complete and typechecks/builds; only
// the live OIDC round-trip through a real identity provider is untested
// in this environment.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type CurrentUser = {
  user_id: string;
};

export default function DashboardPage() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    fetch(`${API_BASE_URL}/auth/me`, { credentials: "include" })
      .then((response) => {
        if (!response.ok) {
          if (!cancelled) {
            window.location.href = "/";
          }
          return null;
        }
        return response.json() as Promise<CurrentUser>;
      })
      .then((data) => {
        if (!cancelled && data) {
          setUser(data);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogout = async () => {
    await fetch(`${API_BASE_URL}/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
    window.location.href = "/";
  };

  if (loading) {
    return <p>Loading...</p>;
  }

  if (!user) {
    return null;
  }

  return (
    <main>
      <p>Logged in as {user.user_id}</p>
      <button onClick={handleLogout}>Log out</button>
    </main>
  );
}
