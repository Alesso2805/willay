import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { settings } from '../settings';
import { Severity } from '../ui/visual-states';

export type RuleType = 'threshold' | 'rate_of_change' | 'silence';
export type ThresholdOperator = 'gt' | 'ge' | 'lt' | 'le';
export type Direction = 'down' | 'up';

export interface ThresholdParams {
  operator: ThresholdOperator;
  value: number;
  consecutive: number;
}

export interface RateOfChangeParams {
  direction: Direction;
  delta: number;
  window_minutes: number;
}

/** K lives in each station's silence_multiplier: a silence rule has no params. */
export type RuleParams = ThresholdParams | RateOfChangeParams | Record<string, never>;

export interface Ref {
  id: string;
  name: string;
}

/** docs/openapi.json › RuleOut. */
export interface Rule {
  id: string;
  type: RuleType;
  zone: Ref;
  /** null: every station of the zone (silence only). */
  station: { id: string; code: string; name: string; unit: string } | null;
  params: RuleParams;
  severity: Severity;
  escalation_policy: Ref;
  cooldown_s: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** docs/openapi.json › ThresholdRuleIn | RateOfChangeRuleIn | SilenceRuleIn. */
export interface RuleInput {
  type: RuleType;
  zone_id: string;
  station_id: string | null;
  params: RuleParams;
  severity: Severity;
  escalation_policy_id: string;
  cooldown_s: number;
  is_active: boolean;
}

export type PreviewInput = Pick<RuleInput, 'type' | 'zone_id' | 'station_id' | 'params'>;

/** docs/openapi.json › PreviewOut. */
export interface RulePreview {
  since: string;
  until: string;
  stations: {
    station: { id: string; code: string; name: string; unit: string };
    readings: { measured_at: string; value: number }[];
    /** When the rule would have opened an incident; value null for silence. */
    firings: { at: string; value: number | null }[];
    truncated: boolean;
  }[];
}

@Injectable({ providedIn: 'root' })
export class RulesApi {
  private readonly http = inject(HttpClient);
  private readonly url = `${settings.apiUrl}/v1/rules`;

  list(includeInactive = false): Observable<Rule[]> {
    return this.http.get<Rule[]>(this.url, { params: { include_inactive: includeInactive } });
  }

  create(rule: RuleInput): Observable<Rule> {
    return this.http.post<Rule>(this.url, rule);
  }

  /** Also reactivates it with `is_active: true`. The type never changes. */
  update(id: string, rule: RuleInput): Observable<Rule> {
    return this.http.put<Rule>(`${this.url}/${id}`, rule);
  }

  /** Deactivates it: incidents keep pointing to it. */
  deactivate(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}`);
  }

  preview(draft: PreviewInput): Observable<RulePreview> {
    return this.http.post<RulePreview>(`${this.url}/preview`, draft);
  }

  /** Every role may read them; the rule form picks one. */
  policies(): Observable<Ref[]> {
    return this.http.get<Ref[]>(`${settings.apiUrl}/v1/escalation-policies`);
  }
}
