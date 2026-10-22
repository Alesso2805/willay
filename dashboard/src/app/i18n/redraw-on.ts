import {
  Directive,
  TemplateRef,
  ViewContainerRef,
  effect,
  inject,
  input,
  untracked,
} from '@angular/core';

/**
 * Draws its content again, from scratch, whenever the value changes:
 * `<ng-container *appRedrawOn="languages.current()">`. A new language thus reaches every text,
 * including those computed in TypeScript, without each page reacting to the change on its own.
 * What lives in services (the session, the live channel) carries on.
 */
@Directive({ selector: '[appRedrawOn]' })
export class RedrawOn {
  readonly appRedrawOn = input.required<unknown>();

  private readonly template = inject(TemplateRef);
  private readonly container = inject(ViewContainerRef);

  constructor() {
    effect(() => {
      this.appRedrawOn();
      untracked(() => {
        this.container.clear();
        this.container.createEmbeddedView(this.template);
      });
    });
  }
}
