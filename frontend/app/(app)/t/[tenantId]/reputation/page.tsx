"use client";

// Reputation hub (UI-11). `lib/nav/config.ts` still lists "Reputation"
// as a planned nav item with no route -- deliberately left that way this
// phase: `product/reputation/routes.py`'s own module docstring says its
// router is not yet mounted in `product/api/main.py` (a documented,
// three-line follow-up, out of scope here -- `product/api/main.py` is a
// protected file for this phase). Every request through this page 404s
// against the real backend until that follow-up lands. This route exists
// and is fully implemented/tested against the real contract so it is
// ready the moment that happens, but it is not linked from navigation
// yet -- see this phase's own implementation/audit report.
//
// Two independent resources, not one flattened view (the API does not
// return them together): review requests (contact outreach asking for a
// review) and reviews (what was actually recorded, manually in this
// phase -- `product/reputation/providers.py`'s own module docstring).
import { useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import {
  ReviewRequestsList,
  CreateReviewRequestForm,
  ReviewsList,
  RecordReviewForm,
} from "@/components/reputation";

export default function ReputationPage() {
  const { tenantId } = useTenant();
  const [createRequestOpen, setCreateRequestOpen] = useState(false);
  const [recordReviewOpen, setRecordReviewOpen] = useState(false);
  const [requestsReloadKey, setRequestsReloadKey] = useState(0);
  const [reviewsReloadKey, setReviewsReloadKey] = useState(0);

  return (
    <Page>
      <PageHeader title="Reputation" description="Request, track, and respond to customer reviews." />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        <section aria-labelledby="requests-heading">
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
            <h2 id="requests-heading" style={{ fontSize: "var(--font-size-md)", margin: 0 }}>
              Review requests
            </h2>
            <Button size="sm" onClick={() => setCreateRequestOpen(true)}>
              Request a review
            </Button>
          </div>
          <ReviewRequestsList
            tenantId={tenantId}
            reloadKey={requestsReloadKey}
            onCreate={
              <Button size="sm" onClick={() => setCreateRequestOpen(true)}>
                Request one now
              </Button>
            }
          />
        </section>

        <section aria-labelledby="reviews-heading">
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
            <h2 id="reviews-heading" style={{ fontSize: "var(--font-size-md)", margin: 0 }}>
              Reviews
            </h2>
            <Button size="sm" onClick={() => setRecordReviewOpen(true)}>
              Record a review
            </Button>
          </div>
          <ReviewsList
            tenantId={tenantId}
            reloadKey={reviewsReloadKey}
            onCreate={
              <Button size="sm" onClick={() => setRecordReviewOpen(true)}>
                Record one now
              </Button>
            }
          />
        </section>
      </div>

      <Dialog open={createRequestOpen} onClose={() => setCreateRequestOpen(false)} title="Request a review">
        <CreateReviewRequestForm
          tenantId={tenantId}
          onSaved={() => {
            setCreateRequestOpen(false);
            setRequestsReloadKey((key) => key + 1);
          }}
        />
      </Dialog>

      <Dialog open={recordReviewOpen} onClose={() => setRecordReviewOpen(false)} title="Record a review">
        <RecordReviewForm
          tenantId={tenantId}
          onSaved={() => {
            setRecordReviewOpen(false);
            setReviewsReloadKey((key) => key + 1);
          }}
        />
      </Dialog>
    </Page>
  );
}
