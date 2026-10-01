import { Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Session } from './session';

const ROLE_LABELS: Record<string, string> = {
  admin: 'Administración',
  operator: 'Operación',
  responder: 'Respuesta',
  viewer: 'Lectura',
};

@Component({
  selector: 'app-home-page',
  imports: [RouterLink],
  template: `
    @if (session.me(); as me) {
      <dl class="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-slate-800">
        <dt class="font-medium">Correo</dt>
        <dd class="min-w-0 break-words">{{ me.email }}</dd>
        <dt class="font-medium">Organización</dt>
        <dd>{{ me.organization_name }}</dd>
        <dt class="font-medium">Zona horaria</dt>
        <dd>{{ me.organization_timezone }}</dd>
        <dt class="font-medium">Roles</dt>
        <dd>{{ roleLabels(me.roles) }}</dd>
      </dl>
      @if (me.permissions.length === 0) {
        <!-- SPEC: sin roles solo se consulta /v1/me, para que el panel explique por qué no ve nada. -->
        <div role="status" class="mt-6 rounded-md border border-slate-300 bg-slate-50 p-4 text-slate-800">
          <p class="font-semibold">Tu usuario todavía no tiene un rol en Vigía</p>
          <p class="mt-1">
            Por eso no ves zonas, estaciones ni incidentes. Pide a quien administra Vigía en tu
            organización que te asigne uno.
          </p>
        </div>
      } @else {
        <p class="mt-6 text-slate-700">
          <a routerLink="/zonas" class="underline">Ver las zonas de riesgo en el mapa</a>
        </p>
      }
    }
  `,
})
export class HomePage {
  protected readonly session = inject(Session);

  protected roleLabels(roles: string[]): string {
    return roles.map((role) => ROLE_LABELS[role] ?? role).join(', ') || 'Sin rol asignado';
  }
}
