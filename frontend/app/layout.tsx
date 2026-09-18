import type { Metadata } from "next";

// Minimal root layout (docs/ROADMAP.md Phase 1.6). No branding here --
// the end-user-facing display name is a white-label runtime configuration
// value, never a hardcoded string in the frontend
// (docs/ADR/0001-naming-and-identifier-neutrality.md, item 3).
export const metadata: Metadata = {
  title: "Product",
  description: "Agency platform -- Phase 1 scaffold.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
