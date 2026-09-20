"use client";

import { useState } from "react";
import { createCompany, updateCompany, type Company } from "@/lib/api/crm";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function CompanyForm({
  tenantId,
  company,
  onSaved,
}: {
  tenantId: string;
  company?: Company;
  onSaved: (company: Company) => void;
}) {
  const [name, setName] = useState(company?.name ?? "");
  const [domain, setDomain] = useState(company?.domain ?? "");
  const [phone, setPhone] = useState(company?.phone ?? "");

  const { state, run } = useAsyncAction(() =>
    company
      ? updateCompany(tenantId, company.id, { name, domain: domain || null, phone: phone || null })
      : createCompany(tenantId, { name, domain: domain || null, phone: phone || null }),
  );

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
      <Input label="Domain" value={domain} onChange={(event) => setDomain(event.target.value)} />
      <Input label="Phone" value={phone} onChange={(event) => setPhone(event.target.value)} />
      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !name.trim()}>
        {state.status === "pending" ? "Saving…" : company ? "Save changes" : "Create company"}
      </Button>
    </form>
  );
}
