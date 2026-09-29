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
        <dd>{{ me.email }}</dd>
        <dt class="font-medium">Organización</dt>
        <dd class="font-mono text-sm">{{ me.organization_id }}</dd>
        <dt class="font-medium">Roles</dt>
        <dd>{{ roleLabels(me.roles) }}</dd>
      </dl>
      <p class="mt-6 text-slate-700">
        <a routerLink="/zonas" class="underline">Ver las zonas de riesgo en el mapa</a>
      </p>
    }
  `,
})
export class HomePage {
  protected readonly session = inject(Session);

  protected roleLabels(roles: string[]): string {
    return roles.map((role) => ROLE_LABELS[role] ?? role).join(', ') || 'Sin rol asignado';
  }
}
