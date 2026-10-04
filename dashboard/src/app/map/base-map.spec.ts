import { plainText } from './base-map';

describe('plainText', () => {
  it('keeps a name as text: markup in it is never parsed (Leaflet inserts strings as HTML)', () => {
    const element = plainText('<img src=x onerror=alert(1)> · riesgo alto');
    expect(element.textContent).toBe('<img src=x onerror=alert(1)> · riesgo alto');
    expect(element.querySelector('img')).toBeNull();
    expect(element.children).toHaveLength(0);
  });
});
