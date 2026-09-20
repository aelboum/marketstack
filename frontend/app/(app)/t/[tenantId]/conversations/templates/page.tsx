"use client";

import Link from "next/link";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { TemplatesPanel } from "@/components/conversations";

export default function ConversationTemplatesPage() {
  const { tenantId } = useTenant();

  return (
    <Page>
      <p style={{ marginTop: 0 }}>
        <Link href={`/t/${tenantId}/conversations`} style={{ fontSize: "var(--font-size-sm)" }}>
          ← Back to conversations
        </Link>
      </p>
      <PageHeader title="Message templates" description="Reusable message bodies for conversations." />
      <TemplatesPanel tenantId={tenantId} />
    </Page>
  );
}
