import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

/** Contacts and their groups are one section with two tabs, so the menu stays short. */
@Component({
  selector: 'app-contact-tabs',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, RouterLinkActive],
  host: { class: 'mb-6 block' },
  template: `
    <nav aria-label="Contactos y grupos" class="flex gap-1 border-b border-slate-200">
      @for (tab of tabs; track tab.path) {
        <a
          [routerLink]="tab.path"
          class="-mb-px border-b-2 border-transparent px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900"
          routerLinkActive="border-brand-700! text-brand-800!"
          [routerLinkActiveOptions]="{ exact: true }"
          ariaCurrentWhenActive="page"
          >{{ tab.label }}</a
        >
      }
    </nav>
  `,
})
export class ContactTabs {
  protected readonly tabs = [
    { path: '/contactos', label: 'Contactos' },
    { path: '/contactos/grupos', label: 'Grupos' },
  ];
}
