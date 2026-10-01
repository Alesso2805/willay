import axe from 'axe-core';

/**
 * Violaciones serias o críticas de axe-core en lo que el componente dibujó (VIG-33). Solo
 * para los tests: Lighthouse usa este mismo motor para su puntaje de accesibilidad.
 *
 * El contraste de color no se mide aquí, porque jsdom no calcula estilos reales. Lo cubren
 * los tests del catálogo visual, que miden cada color de estado y de aviso.
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
