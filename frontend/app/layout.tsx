import type { Metadata, Viewport } from "next";
import { SessionProvider } from "@/lib/auth/session-context";
import "./globals.css";

// Root layout (docs/ROADMAP.md Phase 1.6, extended by UI-1). The
// end-user-facing display name is a white-label runtime configuration
// value, never a hardcoded string in the frontend
// (docs/ADR/0001-naming-and-identifier-neutrality.md, item 3) -- "Product"
// here is the same neutral placeholder Phase 1.6 already used, not a
// UI-1 decision to hardcode branding (that is UI-7's scope).
export const metadata: Metadata = {
  title: "Product",
  description: "Agency platform.",
};

// Declared explicitly (UI-8) rather than left to the framework default,
// so the zoom policy is a deliberate, reviewable decision: pinch-zoom
// stays enabled and no maximum scale is imposed. Disabling either is a
// common accessibility failure for low-vision users, and a silent
// default is easy to regress without anyone noticing.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  userScalable: true,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
