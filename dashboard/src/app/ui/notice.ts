import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { NOTICE_TONES, NoticeTone } from './visual-states';

/**
 * Notice with its tone. An error or a warning is announced immediately
 * (`role="alert"`); information, without interrupting (`role="status"`).
 */
@Component({
  selector: 'app-notice',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'block rounded-md border p-3 text-sm',
    '[attr.role]': "tone() === 'info' ? 'status' : 'alert'",
    '[style.color]': 'palette().foreground',
    '[style.background-color]': 'palette().background',
    '[style.border-color]': 'palette().border',
  },
  template: `<ng-content />`,
})
export class Notice {
  readonly tone = input<NoticeTone>('error');
  protected readonly palette = computed(() => NOTICE_TONES[this.tone()]);
}
