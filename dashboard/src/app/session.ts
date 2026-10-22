import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { Observable, catchError, from, map, of, switchMap } from 'rxjs';
import { Language, TranslationKey, currentLanguage, t } from './i18n/i18n';
import { LanguageService } from './i18n/language';
import { settings } from './settings';

/** GET /v1/me response. */
export interface Me {
  user_id: string;
  email: string;
  full_name: string;
  organization_id: string;
  keycloak_org_id: string;
  organization_name: string;
  /** IANA (e.g. America/Lima): the dashboard shows times in the organization's time zone. */
  organization_timezone: string;
  roles: string[];
  /** Only for hiding actions in the UI: the API checks the permission on every endpoint. */
  permissions: string[];
  /** The dashboard language the user chose; null: never chose one. */
  language: Language | null;
}

const ROLE_LABELS: Readonly<Record<string, TranslationKey>> = {
  admin: 'roles.admin',
  operator: 'roles.operator',
  responder: 'roles.responder',
  viewer: 'roles.viewer',
};

export function roleLabels(roles: readonly string[]): string {
  const labels = roles.map((role) => (ROLE_LABELS[role] ? t(ROLE_LABELS[role]) : role));
  return labels.join(', ') || t('roles.none');
}

export type SessionState =
  | { status: 'loading' }
  | { status: 'anonymous' }
  | { status: 'ready'; me: Me }
  | { status: 'forbidden' } // valid token, but not exactly one organization
  | { status: 'error' };

@Injectable({ providedIn: 'root' })
export class Session {
  private readonly oidc = inject(OidcSecurityService);
  private readonly http = inject(HttpClient);
  private readonly language = inject(LanguageService);

  private readonly _state = signal<SessionState>({ status: 'loading' });
  readonly state = this._state.asReadonly();
  readonly me = computed(() => {
    const state = this._state();
    return state.status === 'ready' ? state.me : null;
  });

  /** Handles the return from Keycloak (if any) and loads /v1/me. */
  start(): void {
    this.oidc
      .checkAuth()
      .pipe(
        switchMap(({ isAuthenticated }) =>
          isAuthenticated ? this.loadMe() : of<SessionState>({ status: 'anonymous' }),
        ),
      )
      .subscribe((state) => this._state.set(state));
  }

  login(): void {
    // Keycloak's sign-in page in the same language as the dashboard (OIDC ui_locales).
    this.oidc.authorize(undefined, { customParams: { ui_locales: currentLanguage() } });
  }

  logout(): void {
    this.oidc.logoff().subscribe();
  }

  /** After an admin changes the organization's time zone: every time on screen follows. */
  useOrganizationTimezone(timezone: string): void {
    const state = this._state();
    if (state.status !== 'ready') return;
    this._state.set({ ...state, me: { ...state.me, organization_timezone: timezone } });
  }

  private loadMe(): Observable<SessionState> {
    return this.http.get<Me>(`${settings.apiUrl}/v1/me`).pipe(
      // The user's language is in place before the first page renders.
      switchMap((me) => from(this.language.adopt(me.language)).pipe(map(() => me))),
      map((me): SessionState => ({ status: 'ready', me })),
      catchError((error: unknown) =>
        of<SessionState>(
          error instanceof HttpErrorResponse && error.status === 403
            ? { status: 'forbidden' }
            : { status: 'error' },
        ),
      ),
    );
  }
}
