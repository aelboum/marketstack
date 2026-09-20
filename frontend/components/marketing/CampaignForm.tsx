"use client";

// Create vs. edit are genuinely different shapes here, not just a
// convenience split: `UpdateCampaignRequest` (`product/marketing
// /routes.py`) has no `channel`/segmentation fields at all -- channel
// and audience are set once, at creation, and never editable afterward
// through this API. Both create and update are also only permitted
// while the campaign is still `"draft"` (`update_campaign()`'s own
// guard) -- the containing page only renders this form for a draft
// campaign; this component doesn't re-check that, it just doesn't
// receive the fields a non-draft edit would need.
import { useState } from "react";
import { createCampaign, updateCampaign, listTemplates, CHANNELS, type Campaign, type Channel, type Template } from "@/lib/api/marketing";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function CampaignForm({
  tenantId,
  campaign,
  onSaved,
}: {
  tenantId: string;
  /** Omit to create; pass the existing (draft) campaign to edit it. */
  campaign?: Campaign;
  onSaved: (campaign: Campaign) => void;
}) {
  const [name, setName] = useState(campaign?.name ?? "");
  const [channel, setChannel] = useState<Channel>(campaign?.channel ?? "email");
  const [subject, setSubject] = useState(campaign?.subject ?? "");
  const [body, setBody] = useState(campaign?.body ?? "");
  const [templateId, setTemplateId] = useState(campaign?.template_id ?? "");
  const [clickTargetUrl, setClickTargetUrl] = useState(campaign?.click_target_url ?? "");
  const [segmentQ, setSegmentQ] = useState("");
  const [segmentTag, setSegmentTag] = useState("");

  const templatesQuery = useApiQuery(() => listTemplates(tenantId, { limit: 100 }), [tenantId]);
  const relevantTemplates: Template[] =
    templatesQuery.status === "success"
      ? templatesQuery.data.results.filter(
          (t) => t.template_type === `${channel === "email" ? "email" : "sms"}_campaign`,
        )
      : [];

  const { state, run } = useAsyncAction(() =>
    campaign
      ? updateCampaign(tenantId, campaign.id, {
          name,
          subject: channel === "email" ? subject || null : null,
          body,
          template_id: templateId || null,
          click_target_url: clickTargetUrl || null,
          update_click_target_url: true,
        })
      : createCampaign(tenantId, {
          name,
          channel,
          body,
          subject: channel === "email" ? subject || null : null,
          segment_q: segmentQ || null,
          segment_tag: segmentTag || null,
          template_id: templateId || null,
          click_target_url: clickTargetUrl || null,
        }),
  );

  const canSubmit = name.trim().length > 0 && body.trim().length > 0;

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!canSubmit) return;
        const saved = await run();
        if (saved) onSaved(saved);
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <Input label="Name" required value={name} onChange={(event) => setName(event.target.value)} />

      {!campaign ? (
        <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
          <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>Channel</span>
          <select value={channel} onChange={(event) => setChannel(event.target.value as Channel)}>
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <p style={{ margin: 0, fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
          Channel: {campaign.channel} (set at creation, not editable)
        </p>
      )}

      {channel === "email" ? (
        <Input label="Subject" value={subject} onChange={(event) => setSubject(event.target.value)} />
      ) : null}

      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          Template (optional -- overwrites body below on save)
        </span>
        <select value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
          <option value="">None</option>
          {relevantTemplates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>Body</span>
        <textarea
          required
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={6}
          style={{ fontFamily: "inherit", fontSize: "var(--font-size-sm)", padding: "var(--space-2)", border: "1px solid var(--color-border-strong)", borderRadius: "var(--radius-sm)" }}
        />
      </label>

      {channel === "email" ? (
        <Input
          label="Click-tracking target URL (optional)"
          value={clickTargetUrl}
          onChange={(event) => setClickTargetUrl(event.target.value)}
          placeholder="https://example.com/offer"
        />
      ) : null}

      {!campaign ? (
        <fieldset style={{ border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", padding: "var(--space-3)" }}>
          <legend style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)", padding: "0 var(--space-1)" }}>
            Audience (set now, not editable after creation)
          </legend>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            <Input
              label="Contact search (optional)"
              value={segmentQ}
              onChange={(event) => setSegmentQ(event.target.value)}
              placeholder="Matches the same search CRM contacts support"
            />
            <Input
              label="Tag (optional)"
              value={segmentTag}
              onChange={(event) => setSegmentTag(event.target.value)}
            />
            <p style={{ margin: 0, fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
              Leave both blank to target every contact.
            </p>
          </div>
        </fieldset>
      ) : null}

      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
      <Button type="submit" disabled={state.status === "pending" || !canSubmit}>
        {state.status === "pending" ? "Saving…" : campaign ? "Save changes" : "Create campaign"}
      </Button>
    </form>
  );
}
