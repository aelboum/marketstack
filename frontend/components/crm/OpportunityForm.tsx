"use client";

// Create and edit -- but unlike contacts/companies, `UpdateOpportunityRequest`
// (`product/crm/routes.py`) only accepts `name`/`amount_decimal`/
// `amount_currency`: pipeline/stage/contact/company are set at creation
// and changed afterward only via the dedicated `POST .../stage` endpoint
// (stage) -- there is no way to move an opportunity to a different
// pipeline, or re-link its contact/company, once created. This form
// reflects that real constraint rather than offering a control with
// nowhere to send its value.
import { useEffect, useState } from "react";
import {
  createOpportunity,
  listContacts,
  listCompanies,
  listPipelines,
  listStages,
  updateOpportunity,
  type Company,
  type Contact,
  type Opportunity,
  type Pipeline,
  type Stage,
} from "@/lib/api/crm";
import { parseMoney } from "@/lib/crm/money";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function OpportunityForm({
  tenantId,
  opportunity,
  onSaved,
}: {
  tenantId: string;
  opportunity?: Opportunity;
  onSaved: (opportunity: Opportunity) => void;
}) {
  const parsedAmount = parseMoney(opportunity?.amount ?? null);
  const [name, setName] = useState(opportunity?.name ?? "");
  const [amountDecimal, setAmountDecimal] = useState(parsedAmount?.decimal ?? "");
  const [amountCurrency, setAmountCurrency] = useState(parsedAmount?.currency ?? "USD");
  const [pipelineId, setPipelineId] = useState(opportunity?.pipeline_id ?? "");
  const [stageId, setStageId] = useState(opportunity?.stage_id ?? "");
  const [contactId, setContactId] = useState(opportunity?.contact_id ?? "");
  const [companyId, setCompanyId] = useState(opportunity?.company_id ?? "");

  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [stages, setStages] = useState<Stage[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);

  // Reference data for the create-time selects -- not needed when
  // editing, since those fields are immutable on edit (see module note).
  useEffect(() => {
    if (opportunity) return;
    let cancelled = false;
    listPipelines(tenantId).then((result) => {
      if (!cancelled) setPipelines(result);
    });
    listContacts(tenantId, { limit: 100 }).then((result) => {
      if (!cancelled) setContacts(result.results);
    });
    listCompanies(tenantId, { limit: 100 }).then((result) => {
      if (!cancelled) setCompanies(result.results);
    });
    return () => {
      cancelled = true;
    };
  }, [tenantId, opportunity]);

  useEffect(() => {
    if (opportunity || !pipelineId) return;
    let cancelled = false;
    listStages(tenantId, pipelineId).then((result) => {
      if (!cancelled) setStages(result);
    });
    return () => {
      cancelled = true;
    };
  }, [tenantId, pipelineId, opportunity]);

  const { state, run } = useAsyncAction(() =>
    opportunity
      ? updateOpportunity(tenantId, opportunity.id, {
          name,
          amount_decimal: amountDecimal || null,
          amount_currency: amountDecimal ? amountCurrency : null,
        })
      : createOpportunity(tenantId, {
          name,
          pipeline_id: pipelineId,
          stage_id: stageId,
          contact_id: contactId || null,
          company_id: companyId || null,
          amount_decimal: amountDecimal || null,
          amount_currency: amountDecimal ? amountCurrency : null,
        }),
  );

  const canSubmit = opportunity
    ? name.trim().length > 0
    : name.trim().length > 0 && pipelineId.length > 0 && stageId.length > 0;

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        const saved = await run();
        if (saved) onSaved(saved);
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <Input label="Name" required value={name} onChange={(event) => setName(event.target.value)} />

      <div style={{ display: "flex", gap: "var(--space-2)" }}>
        <div style={{ flex: 2 }}>
          <Input
            label="Amount"
            value={amountDecimal}
            onChange={(event) => setAmountDecimal(event.target.value)}
            placeholder="1500.00"
          />
        </div>
        <div style={{ flex: 1 }}>
          <Input
            label="Currency"
            value={amountCurrency}
            onChange={(event) => setAmountCurrency(event.target.value.toUpperCase())}
            maxLength={3}
          />
        </div>
      </div>

      {!opportunity ? (
        <>
          <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
              Pipeline
            </span>
            <select
              required
              value={pipelineId}
              onChange={(event) => {
                setPipelineId(event.target.value);
                setStageId("");
              }}
            >
              <option value="">Choose…</option>
              {pipelines.map((pipeline) => (
                <option key={pipeline.id} value={pipeline.id}>
                  {pipeline.name}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
              Stage
            </span>
            <select
              required
              value={stageId}
              onChange={(event) => setStageId(event.target.value)}
              disabled={!pipelineId}
            >
              <option value="">Choose…</option>
              {stages.map((stage) => (
                <option key={stage.id} value={stage.id}>
                  {stage.name}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
              Contact (optional)
            </span>
            <select value={contactId} onChange={(event) => setContactId(event.target.value)}>
              <option value="">None</option>
              {contacts.map((contact) => (
                <option key={contact.id} value={contact.id}>
                  {contact.first_name} {contact.last_name}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
              Company (optional)
            </span>
            <select value={companyId} onChange={(event) => setCompanyId(event.target.value)}>
              <option value="">None</option>
              {companies.map((company) => (
                <option key={company.id} value={company.id}>
                  {company.name}
                </option>
              ))}
            </select>
          </label>
        </>
      ) : null}

      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !canSubmit}>
        {state.status === "pending" ? "Saving…" : opportunity ? "Save changes" : "Create opportunity"}
      </Button>
    </form>
  );
}
