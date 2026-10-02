import { convertToParamMap } from '@angular/router';
import { filterFromUrl, filterToUrl } from './inbox-filter';

describe('inbox filter', () => {
  it('opens with open and acknowledged incidents of every severity', () => {
    expect(filterFromUrl(convertToParamMap({}))).toEqual({
      statuses: ['open', 'acknowledged'],
      severities: [],
    });
  });

  it('reads the URL, ignores unknown values and keeps a stable order', () => {
    const params = convertToParamMap({
      estado: ['resolved', 'open', 'closed'],
      severidad: ['info', 'urgent', 'critical'],
    });
    expect(filterFromUrl(params)).toEqual({
      statuses: ['open', 'resolved'],
      severities: ['critical', 'info'],
    });
    // Only unknown statuses: as if there were none.
    expect(filterFromUrl(convertToParamMap({ estado: 'closed' })).statuses).toEqual([
      'open',
      'acknowledged',
    ]);
  });

  it('writes a clean URL for the default and the values otherwise', () => {
    expect(filterToUrl({ statuses: ['acknowledged', 'open'], severities: [] })).toEqual({
      estado: null,
      severidad: null,
    });
    expect(filterToUrl({ statuses: ['resolved', 'open'], severities: ['warning'] })).toEqual({
      estado: ['open', 'resolved'],
      severidad: ['warning'],
    });
  });
});
