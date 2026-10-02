import { Component, computed, effect, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { NewIncidents } from './incidents/new-incidents';
import { visibleNavItems } from './navigation';
import { LiveEvents } from './realtime/live-events';
import { Session, roleLabels } from './session';
import { Icon } from './ui/icon';
import { Notice } from './ui/notice';
import { StateBadge } from './ui/state-badge';
import { CONNECTION_STATES } from './ui/visual-states';

@Component({
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Icon, Notice, StateBadge, NewIncidents],
  selector: 'app-root',
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App {
  protected readonly session = inject(Session);
  protected readonly live = inject(LiveEvents);
  protected readonly connection = computed(() => {
    const status = this.live.status();
    return status === 'off' ? null : CONNECTION_STATES[status];
  });
  protected readonly navItems = computed(() =>
    visibleNavItems(this.session.me()?.permissions ?? []),
  );
  /** Only matters on narrow screens: from `lg` up the navigation is a fixed sidebar. */
  protected readonly menuOpen = signal(false);
  protected readonly roles = roleLabels;
  /** SPEC, ethical risk: the product must say this on every screen. */
  protected readonly disclaimer =
    'Herramienta de apoyo para detectar, decidir y avisar. No reemplaza a los sistemas ' +
    'oficiales de alerta (INDECI, COER regionales, SISMATE).';

  constructor() {
    this.session.start();
    // One live channel per session, and only for users who may see what it announces.
    effect(() => {
      if (this.session.me()?.permissions.includes('view')) this.live.connect();
      else this.live.disconnect();
    });
  }

  protected toggleMenu(): void {
    this.menuOpen.update((open) => !open);
  }
}
