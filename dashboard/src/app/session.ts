import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { Observable, catchError, map, of, switchMap } from 'rxjs';
import { settings } from './settings';

/** Respuesta de GET /v1/me. */
export interface Me {
  user_id: string;
  email: string;
  full_name: string;
  organization_id: string;
  keycloak_org_id: string;
  organization_name: string;
  /** IANA (p. ej. America/Lima): el panel muestra las horas en la zona de la organización. */
  organization_timezone: string;
  roles: string[];
  /** Solo para ocultar acciones en la UI: la API valida el permiso en cada endpoint. */
  permissions: string[];
}

export type SessionState =
  | { status: 'loading' }
  | { status: 'anonymous' }
  | { status: 'ready'; me: Me }
  | { status: 'forbidden' } // token válido, pero sin exactamente una organización
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

  /** Procesa el retorno de Keycloak (si lo hay) y carga /v1/me. */
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
