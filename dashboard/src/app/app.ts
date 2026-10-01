import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { visibleNavItems } from './navigation';
import { Session } from './session';
import { Icon } from './ui/icon';

@Component({
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Icon],
  selector: 'app-root',
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App {
  protected readonly session = inject(Session);
  protected readonly navItems = computed(() =>
    visibleNavItems(this.session.me()?.permissions ?? []),
  );
  /** Solo cuenta en pantallas angostas: desde `sm` la navegación siempre se ve. */
  protected readonly menuOpen = signal(false);

  constructor() {
    this.session.start();
  }

  protected toggleMenu(): void {
    this.menuOpen.update((open) => !open);
  }
}
