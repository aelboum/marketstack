import { Page } from "./Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { EmptyState } from "@/components/ui/states";

// Shared shape for every UI-1 domain placeholder (CRM/Conversations/
// Marketing/Appointments) -- proves the shell/navigation/Page container
// is reusable across modules without four divergent implementations.
// Each module's real interface (UI-3-UI-6) replaces its one page's body,
// never this component or the shell around it.
export function DomainPlaceholder({
  title,
  description,
  uiPhase,
}: {
  title: string;
  description: string;
  uiPhase: string;
}) {
  return (
    <Page>
      <PageHeader title={title} description={description} />
      <EmptyState
        title={`${title} isn't built yet`}
        description={`This module's real interface, using the existing ${title} backend API, is ${uiPhase}'s scope -- not UI-1's. This placeholder only proves the application shell is reusable.`}
      />
    </Page>
  );
}
