// @ts-expect-error the dashboard has no Node types: this test reads the templates from disk
import { readFileSync, readdirSync } from 'node:fs';
import {
  TmplAstRecursiveVisitor,
  type TmplAstText,
  type TmplAstTextAttribute,
  parseTemplate,
  tmplAstVisitAll,
} from '@angular/compiler';

/**
 * VIG-40: every text a person reads comes from the translation files. Each template, in its
 * own file or inline, is parsed with Angular's own parser: any text node, or any attribute a
 * person reads, with a letter in it and not bound to `t(...)`, is a hard-coded string.
 */

const ROOT = 'src/app';
/** Attributes read aloud or shown: they must be translated like any text. */
const READ_BY_PEOPLE = new Set(['aria-label', 'aria-description', 'title', 'placeholder', 'alt']);
/** The same in every language: the brand, the demo's accounts, a station code as an example. */
const NAMES = new Set(['Willay', 'demo-admin', 'demo-operator', 'demo-viewer', 'RIM-CHA-02']);

function templates(): { file: string; source: string }[] {
  const files: string[] = readdirSync(ROOT, { recursive: true }).map((f: string) =>
    f.replaceAll('\\', '/'),
  );
  const found: { file: string; source: string }[] = [];
  for (const file of files) {
    if (file.endsWith('.spec.ts') || !/\.(ts|html)$/.test(file)) continue;
    const text: string = readFileSync(`${ROOT}/${file}`, 'utf8');
    if (file.endsWith('.html')) found.push({ file, source: text });
    if (file.endsWith('.ts')) {
      for (const [, source] of text.matchAll(/template:\s*`([\s\S]*?)`/g)) {
        found.push({ file, source });
      }
    }
  }
  return found;
}

class HardCoded extends TmplAstRecursiveVisitor {
  readonly found: string[] = [];

  constructor(private readonly file: string) {
    super();
  }

  override visitText(text: TmplAstText): void {
    this.check(text.value);
  }

  override visitTextAttribute(attribute: TmplAstTextAttribute): void {
    if (READ_BY_PEOPLE.has(attribute.name)) this.check(attribute.value, attribute.name);
  }

  private check(value: string, attribute?: string): void {
    const words = value.trim();
    if (/\p{L}/u.test(words) && !NAMES.has(words)) {
      this.found.push(`${this.file}: ${attribute ? `${attribute}="${words}"` : `"${words}"`}`);
    }
  }
}

describe('translations', () => {
  it('finds the templates it checks', () => {
    expect(templates().length).toBeGreaterThan(30);
  });

  it('leaves no text a person reads hard-coded in a template', () => {
    const found: string[] = [];
    for (const { file, source } of templates()) {
      const parsed = parseTemplate(source, file, { preserveWhitespaces: false });
      expect(parsed.errors ?? [], file).toEqual([]);
      const visitor = new HardCoded(file);
      tmplAstVisitAll(visitor, parsed.nodes);
      found.push(...visitor.found);
    }
    expect(found).toEqual([]);
  });
});
