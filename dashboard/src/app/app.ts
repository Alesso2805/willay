import { Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { Session } from './session';

const ROLE_LABELS: Record<string, string> = {
  admin: 'Administración',
  operator: 'Operación',
  responder: 'Respuesta',
  viewer: 'Lectura',
};

@Component({
  imports: [RouterOutlet],
  selector: 'app-root',
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App {
  protected readonly session = inject(Session);

  constructor() {
    this.session.start();
  }

  protected roleLabels(roles: string[]): string {
    return roles.map((role) => ROLE_LABELS[role] ?? role).join(', ') || 'Sin rol asignado';
  }
}
