import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { visibleNavItems } from './navigation';
import { Session, roleLabels } from './session';
import { Icon } from './ui/icon';
import { Notice } from './ui/notice';

@Component({
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Icon, Notice],
  selector: 'app-root',
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App {
  protected readonly session = inject(Session);
  protected readonly navItems = computed(() =>
    visibleNavItems(this.session.me()?.permissions ?? []),
  );
  /** Solo cuenta en pantallas angostas: desde `lg` la navegación es una barra lateral fija. */
  protected readonly menuOpen = signal(false);
  protected readonly roles = roleLabels;
  /** SPEC, riesgo ético: el producto debe decirlo en todas sus pantallas. */
  protected readonly disclaimer =
    'Herramienta de apoyo para detectar, decidir y avisar. No reemplaza a los sistemas ' +
    'oficiales de alerta (INDECI, COER regionales, SISMATE).';

  constructor() {
    this.session.start();
  }

  protected toggleMenu(): void {
    this.menuOpen.update((open) => !open);
  }
}
