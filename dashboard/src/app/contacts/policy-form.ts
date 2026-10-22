import { HttpErrorResponse } from '@angular/common/http';
import { t } from '../i18n/i18n';
import { Channel, Policy, PolicyInput } from './policies.api';

export const CHANNELS: readonly Channel[] = ['email', 'telegram'];

/** A level being edited: the wait in minutes as typed, and its targets as "group:channel". */
export interface LevelDraft {
  minutes: string;
  targets: ReadonlySet<string>;
}

/** Problems shown next to their field. */
export interface FormErrors {
  name?: string;
  levels?: string;
  /** By level index. */
  perLevel: Record<number, { wait?: string; targets?: string }>;
}

export function targetKey(groupId: string, channel: Channel): string {
  return `${groupId}:${channel}`;
}

/** 120 -> "2", 90 -> "1.5": the wait in minutes, as SPEC asks the screen to show it. */
export function minutesOf(waitS: number): string {
  return String(Math.round((waitS / 60) * 100) / 100);
}

export function draftsOf(policy: Policy): LevelDraft[] {
  return policy.levels.map((level) => ({
    minutes: minutesOf(level.wait_s),
    targets: new Set(level.targets.map((t) => targetKey(t.contact_group_id, t.channel))),
  }));
}

/** What the API gets. An empty or unreadable wait goes as 0 seconds, for the API to explain. */
export function inputOf(name: string, levels: readonly LevelDraft[]): PolicyInput {
  return {
    name: name.trim(),
    levels: levels.map((level) => {
      const minutes = Number(level.minutes.replace(',', '.'));
      return {
        wait_s: Number.isFinite(minutes) ? Math.round(minutes * 60) : 0,
        targets: [...level.targets].map((key) => {
          const [contact_group_id, channel] = key.split(':') as [string, Channel];
          return { contact_group_id, channel };
        }),
      };
    }),
  };
}

/** Where each problem of a 422 or 409 goes: the API says which field (FastAPI's `loc`). */
export function formErrors(error: unknown): FormErrors | null {
  if (!(error instanceof HttpErrorResponse)) return null;
  const detail = error.error?.detail;
  if (error.status === 409 && typeof detail === 'string') {
    return { name: detail, perLevel: {} };
  }
  if (error.status !== 422 || !Array.isArray(detail)) return null;
  const errors: FormErrors = { perLevel: {} };
  for (const item of detail as { loc?: unknown[]; msg?: string; code?: string }[]) {
    const [, field, index, sub] = item.loc ?? [];
    // The API counts the wait in seconds; this screen asks for minutes.
    const message =
      item.code === 'policy_level_wait'
        ? t('policies.waitRange', { n: typeof index === 'number' ? index + 1 : 1 })
        : (item.msg ?? t('policies.check'));
    if (field === 'name') errors.name = message;
    else if (field === 'levels' && typeof index === 'number') {
      const level = (errors.perLevel[index] ??= {});
      if (sub === 'wait_s') level.wait = message;
      else level.targets = message;
    } else errors.levels = message;
  }
  return errors;
}
