import { describe, it, expect } from 'vitest';
import { batchRoutes, eligibleRecoveryItems, batchPriceLabel } from './batch-run';

describe('batch opt-in', () => {
  it('does not override immediate models or invent unknown prices', () => {
    const routes = batchRoutes('openai', 'gpt-6-luna');
    expect(routes.tailoring.model).toBe('gpt-6-luna');
    expect(Object.keys(routes)).toHaveLength(6);
    expect(batchPriceLabel(null, null)).toContain('unknown');
    expect(batchPriceLabel(.05, .25)).toContain('0.05');
  });
  it('never selects completed or uncertain work for recovery', () => {
    expect(eligibleRecoveryItems([{id:'a',state:'succeeded'}, {id:'b',state:'failed'},
      {id:'c',state:'submission_unknown'}, {id:'d',state:'waiting'}])).toEqual(['b']);
  });
});
