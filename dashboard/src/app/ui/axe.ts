import axe from 'axe-core';

/**
 * Serious or critical axe-core violations in what the component rendered. Tests only:
 * Lighthouse uses this same engine for its accessibility score.
 *
 * Color contrast is not checked here because jsdom does not compute real styles. The visual
 * catalog tests cover it by measuring every state and notice color.
 */
export async function seriousViolations(element: Element): Promise<string[]> {
  const result = await axe.run(element, {
    rules: { 'color-contrast': { enabled: false } },
    resultTypes: ['violations'],
  });
  return result.violations
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map((violation) => `${violation.id}: ${violation.help} (${violation.nodes.length})`);
}
