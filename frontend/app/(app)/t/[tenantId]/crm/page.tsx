"use client";

// CRM hub (UI-3, replaces the UI-1 placeholder). Links into the actual
// implemented sections rather than a single mega-page -- each section is
// its own route so loading/error/pagination state stays scoped to what
// the user is actually looking at.
import Link from "next/link";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";

const SECTIONS = [
  { key: "contacts", label: "Contacts", description: "People associated with this tenant." },
  { key: "companies", label: "Companies", description: "Organizations associated with this tenant." },
  {
    key: "opportunities",
    label: "Opportunities",
    description: "Deals moving through your pipelines.",
  },
  { key: "pipelines", label: "Pipelines", description: "Configure pipelines and stages." },
];

export default function CrmHubPage() {
  const { tenantId } = useTenant();

  return (
    <Page>
      <PageHeader title="CRM" description="Contacts, companies, opportunities, and pipelines." />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
          gap: "var(--space-3)",
        }}
      >
        {SECTIONS.map((section) => (
          <Link key={section.key} href={`/t/${tenantId}/crm/${section.key}`} style={{ textDecoration: "none" }}>
            <Card>
              <strong>{section.label}</strong>
              <p style={{ margin: "var(--space-2) 0 0", fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
                {section.description}
              </p>
            </Card>
          </Link>
        ))}
      </div>
    </Page>
  );
}
