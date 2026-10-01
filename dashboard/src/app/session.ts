import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { Observable, catchError, map, of, switchMap } from 'rxjs';
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
}

const ROLE_LABELS: Record<string, string> = {
  admin: 'Administración',
  operator: 'Operación',
  responder: 'Respuesta',
  viewer: 'Lectura',
};

export function roleLabels(roles: readonly string[]): string {
  return roles.map((role) => ROLE_LABELS[role] ?? role).join(', ') || 'Sin rol asignado';
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
    this.oidc.authorize();
  }

  logout(): void {
    this.oidc.logoff().subscribe();
  }

  private loadMe(): Observable<SessionState> {
    return this.http.get<Me>(`${settings.apiUrl}/v1/me`).pipe(
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
