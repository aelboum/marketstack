"use client";

// Application root / post-login dispatcher (docs/ROADMAP.md Phase 1.6,
// restyled in UI-1). `AUTH_POST_LOGIN_PATH=/` lands every browser back
// here after the OIDC callback (see docker-compose.yml's single-origin
// edge), and ZITADEL's own bootstrap-registered redirect target has no
// other landing spot, so this page must handle both outcomes of a
// session check rather than assume one:
//
//   - authenticated -> hand off to the existing tenant-resolution entry
//     point (`app/dashboard/page.tsx`) rather than re-implementing
//     last-tenant/manual-tenant-id/create-agency logic here;
//   - unauthenticated -> hand off to the product-owned sign-in page
//     (`app/login/page.tsx`, docs/ADR/0016) rather than duplicating its
//     branded card/"Sign in" action here.
//
// This page renders no content of its own beyond a loading state --
// "use client" only because the dispatch needs `useSession()`.
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "@/lib/auth/session-context";
import { LoadingState } from "@/components/ui/states";

export default function HomePage() {
  const { status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") {
      router.replace("/dashboard");
    } else if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [status, router]);

  // Every status renders the same loading state -- there is nothing to
  // show here itself, only ever a brief hop to /dashboard or /login.
  return (
    <main className="full-page-center">
      <LoadingState label="Loading…" />
    </main>
  );
}
