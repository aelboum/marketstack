"use client";

// Website detail. Composes the website's own identity/domain and its
// pages -- two separately-fetched resources (the website endpoint does
// not embed its pages).
import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { getWebsite } from "@/lib/api/websites";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { WebsiteDetailCard, PagesList, CreatePageForm } from "@/components/websites";

export default function WebsiteDetailPage() {
  const { tenantId, websiteId } = useParams<{ tenantId: string; websiteId: string }>();
  const router = useRouter();
  const [createPageOpen, setCreatePageOpen] = useState(false);
  const [pagesReloadKey, setPagesReloadKey] = useState(0);

  const websiteQuery = useApiQuery(() => getWebsite(tenantId, websiteId), [tenantId, websiteId]);

  if (websiteQuery.status === "loading") {
    return (
      <Page>
        <LoadingState label="Loading website…" />
      </Page>
    );
  }
  if (websiteQuery.status === "error") {
    return (
      <Page>
        <ApiErrorPanel error={websiteQuery.error} onRetry={websiteQuery.refetch} />
      </Page>
    );
  }

  const website = websiteQuery.data;

  return (
    <Page>
      <p style={{ marginTop: 0 }}>
        <Link href={`/t/${tenantId}/websites`} style={{ fontSize: "var(--font-size-sm)" }}>
          ← Back to websites
        </Link>
      </p>
      <PageHeader title={website.name} />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        <section aria-labelledby="detail-heading">
          <h2 id="detail-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Details
          </h2>
          <WebsiteDetailCard
            tenantId={tenantId}
            website={website}
            onChanged={() => websiteQuery.refetch()}
            onDeleted={() => router.push(`/t/${tenantId}/websites`)}
          />
        </section>

        <section aria-labelledby="pages-heading">
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: "var(--space-2)",
              flexWrap: "wrap",
              marginBottom: "var(--space-3)",
            }}
          >
            <h2 id="pages-heading" style={{ fontSize: "var(--font-size-md)", margin: 0 }}>
              Pages
            </h2>
            <Button size="sm" onClick={() => setCreatePageOpen(true)}>
              New page
            </Button>
          </div>
          <PagesList
            tenantId={tenantId}
            websiteId={website.id}
            reloadKey={pagesReloadKey}
            onCreate={
              <Button size="sm" onClick={() => setCreatePageOpen(true)}>
                Create a page
              </Button>
            }
          />
        </section>
      </div>

      <Dialog open={createPageOpen} onClose={() => setCreatePageOpen(false)} title="New page">
        <CreatePageForm
          tenantId={tenantId}
          websiteId={website.id}
          onSaved={() => {
            setCreatePageOpen(false);
            setPagesReloadKey((key) => key + 1);
          }}
        />
      </Dialog>
    </Page>
  );
}
