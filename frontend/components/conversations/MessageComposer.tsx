"use client";

// Two genuinely different operations, kept visually distinct rather than
// one control that quietly does different things per channel:
//
// - "Internal note" -- `POST .../messages` (`is_internal_note: true`).
//   Available on every channel. Never delivered anywhere -- logging
//   only (`product/conversations/messages.py`'s own isolation
//   guarantee).
// - "Send email" -- `POST .../send-email`. The only real delivery
//   operation this API exposes; shown only for `channel === "email"`.
//
// There is no send-sms/send-whatsapp route (verified by reading
// `product/conversations/routes.py`: only `email_sending.py` is wired
// to a route) -- for those channels this composer offers only the
// internal-note form, with an explicit note saying why, rather than a
// "Send" button that would silently just log an unsent row.
import { useState } from "react";
import { createMessage, sendEmail, listTemplates, type Channel, MAX_MESSAGE_BODY_LENGTH } from "@/lib/api/conversations";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";
import styles from "./MessageComposer.module.css";

const CHANNEL_NL: Record<Channel, string> = {
  email: "e-mail",
  sms: "sms",
  whatsapp: "WhatsApp",
  chat: "chat",
};

function CharCount({ value }: { value: string }) {
  const over = value.length > MAX_MESSAGE_BODY_LENGTH;
  return (
    <span style={{ fontSize: "var(--font-size-xs)", color: over ? "var(--color-danger)" : "var(--color-text-faint)" }}>
      {value.length} / {MAX_MESSAGE_BODY_LENGTH}
    </span>
  );
}

function TemplatePicker({
  tenantId,
  channel,
  onPick,
}: {
  tenantId: string;
  channel: Channel;
  onPick: (body: string) => void;
}) {
  const query = useApiQuery(() => listTemplates(tenantId), [tenantId]);
  if (query.status !== "success" || query.data.length === 0) return null;

  const relevant = query.data.filter((t) => t.channel === null || t.channel === channel);
  if (relevant.length === 0) return null;

  return (
    <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
      <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
        Sjabloon invoegen
      </span>
      <select
        value=""
        onChange={(event) => {
          const template = relevant.find((t) => t.id === event.target.value);
          if (template) onPick(template.body);
        }}
      >
        <option value="">Kiezen…</option>
        {relevant.map((template) => (
          <option key={template.id} value={template.id}>
            {template.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function InternalNoteForm({
  tenantId,
  threadId,
  channel,
  onSent,
}: {
  tenantId: string;
  threadId: string;
  channel: Channel;
  onSent: () => void;
}) {
  const [body, setBody] = useState("");
  const { state, run } = useAsyncAction(() =>
    createMessage(tenantId, threadId, { direction: "outbound", is_internal_note: true, body }),
  );
  const overLimit = body.length > MAX_MESSAGE_BODY_LENGTH;

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!body.trim() || overLimit) return;
        const created = await run();
        if (created) {
          setBody("");
          onSent();
        }
      }}
      className={styles.form}
    >
      <TemplatePicker tenantId={tenantId} channel={channel} onPick={setBody} />
      <div className={styles.replyRow}>
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={2}
          aria-label="Internal note"
          placeholder="Alleen zichtbaar voor je team -- nooit verzonden naar de klant."
          className={styles.textarea}
          data-invalid={overLimit}
        />
        <Button type="submit" disabled={state.status === "pending" || !body.trim() || overLimit}>
          {state.status === "pending" ? "Bezig…" : "Notitie toevoegen"}
        </Button>
      </div>
      <div className={styles.footerRow}>
        <CharCount value={body} />
      </div>
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
    </form>
  );
}

function SendEmailForm({
  tenantId,
  threadId,
  channel,
  onSent,
}: {
  tenantId: string;
  threadId: string;
  channel: Channel;
  onSent: () => void;
}) {
  const [toEmail, setToEmail] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const { state, run } = useAsyncAction(() => sendEmail(tenantId, threadId, { to_email: toEmail, subject, body }));
  const overLimit = body.length > MAX_MESSAGE_BODY_LENGTH;
  const canSend = toEmail.trim() && subject.trim() && body.trim() && !overLimit;

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!canSend) return;
        const sent = await run();
        if (sent) {
          setBody("");
          setSubject("");
          onSent();
        }
      }}
      className={styles.form}
    >
      <TemplatePicker tenantId={tenantId} channel={channel} onPick={setBody} />
      <Input label="Aan" type="email" required value={toEmail} onChange={(event) => setToEmail(event.target.value)} />
      <Input label="Onderwerp" required value={subject} onChange={(event) => setSubject(event.target.value)} />
      <div className={styles.replyRow}>
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={2}
          aria-label="Email body"
          placeholder="Schrijf een antwoord…"
          className={styles.textarea}
          data-invalid={overLimit}
        />
        <Button type="submit" disabled={state.status === "pending" || !canSend}>
          {state.status === "pending" ? "Versturen…" : "Versturen"}
        </Button>
      </div>
      <div className={styles.footerRow}>
        <CharCount value={body} />
      </div>
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
    </form>
  );
}

export function MessageComposer({
  tenantId,
  threadId,
  channel,
  onSent,
}: {
  tenantId: string;
  threadId: string;
  channel: Channel;
  onSent: () => void;
}) {
  const [tab, setTab] = useState<"note" | "send">(channel === "email" ? "send" : "note");

  return (
    <div className={styles.composer}>
      {/* `variant` alone made the selected tab a colour-only signal.
          `aria-pressed` states it outright, matching the pattern
          AvailableSlotsPicker already uses for its slot toggles. */}
      <div className={styles.tabs}>
        {channel === "email" ? (
          <Button
            variant={tab === "send" ? "primary" : "ghost"}
            size="sm"
            aria-pressed={tab === "send"}
            onClick={() => setTab("send")}
          >
            Antwoord
          </Button>
        ) : null}
        <Button
          variant={tab === "note" ? "primary" : "ghost"}
          size="sm"
          aria-pressed={tab === "note"}
          onClick={() => setTab("note")}
        >
          Interne notitie
        </Button>
      </div>

      {tab === "send" && channel === "email" ? (
        <SendEmailForm tenantId={tenantId} threadId={threadId} channel={channel} onSent={onSent} />
      ) : (
        <>
          {channel !== "email" ? (
            <InlineNotice tone="neutral">
              Er is geen manier om een echt {CHANNEL_NL[channel]}-bericht via dit product te
              versturen -- alleen een inkomende webhook bestaat voor dit kanaal. Een interne notitie
              wordt hier vastgelegd, nooit verzonden naar de klant.
            </InlineNotice>
          ) : null}
          <InternalNoteForm tenantId={tenantId} threadId={threadId} channel={channel} onSent={onSent} />
        </>
      )}
    </div>
  );
}
