"use client";

// Page (content page) detail -- draft editing, publish/unpublish,
// delete. Reached only through its own website (`getPage()` is a flat
// `/pages/{id}` lookup, but this route still nests under
// `/websites/{websiteId}` for a "Back to website" link that makes sense).
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { getPage } from "@/lib/api/websites";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { PageDetailCard } from "@/components/websites";

export default function WebsitePageDetailPage() {
  const { tenantId, websiteId, pageId } = useParams<{
    tenantId: string;
    websiteId: string;
    pageId: string;
  }>();
  const router = useRouter();

  const pageQuery = useApiQuery(() => getPage(tenantId, pageId), [tenantId, pageId]);

  if (pageQuery.status === "loading") {
    return (
      <Page>
        <LoadingState label="Loading page…" />
      </Page>
    );
  }
  if (pageQuery.status === "error") {
    return (
      <Page>
        <ApiErrorPanel error={pageQuery.error} onRetry={pageQuery.refetch} />
      </Page>
    );
  }

  const contentPage = pageQuery.data;

  return (
    <Page>
      <p style={{ marginTop: 0 }}>
        <Link href={`/t/${tenantId}/websites/${websiteId}`} style={{ fontSize: "var(--font-size-sm)" }}>
          ← Back to website
        </Link>
      </p>
      <PageHeader title={contentPage.title} />

      <PageDetailCard
        tenantId={tenantId}
        page={contentPage}
        onChanged={() => pageQuery.refetch()}
        onDeleted={() => router.push(`/t/${tenantId}/websites/${websiteId}`)}
      />
    </Page>
  );
}
