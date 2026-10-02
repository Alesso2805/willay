import { ParamMap, Params } from '@angular/router';
import { IncidentSeverity, IncidentStatus } from './incidents.api';

export const STATUS_OPTIONS: readonly IncidentStatus[] = ['open', 'acknowledged', 'resolved'];
/** Most severe first, as the filter shows them. */
export const SEVERITY_OPTIONS: readonly IncidentSeverity[] = ['critical', 'warning', 'info'];
/** What needs attention: the inbox opens with these (SPEC). */
export const DEFAULT_STATUSES: readonly IncidentStatus[] = ['open', 'acknowledged'];

export interface InboxFilter {
  statuses: IncidentStatus[];
  /** Empty: every severity. */
  severities: IncidentSeverity[];
}

/**
 * The filter lives in the URL (?estado=…&severidad=…), so a shared link shows the same list.
 * Unknown values are ignored; without any status, the inbox shows open and acknowledged.
 */
export function filterFromUrl(params: ParamMap): InboxFilter {
  const statuses = STATUS_OPTIONS.filter((status) => params.getAll('estado').includes(status));
  const severities = SEVERITY_OPTIONS.filter((severity) => params.getAll('severidad').includes(severity));
  return { statuses: statuses.length > 0 ? statuses : [...DEFAULT_STATUSES], severities };
}

/** Query params for a filter; the default leaves the URL clean. */
export function filterToUrl(filter: InboxFilter): Params {
  const isDefault =
    filter.statuses.length === DEFAULT_STATUSES.length &&
    DEFAULT_STATUSES.every((status) => filter.statuses.includes(status));
  return {
    estado: isDefault ? null : STATUS_OPTIONS.filter((status) => filter.statuses.includes(status)),
    severidad: filter.severities.length > 0 ? filter.severities : null,
  };
}
