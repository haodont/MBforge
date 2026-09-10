import { describe, expect, it } from 'vitest'

import { basicValidate } from '../moleculeUtils'

describe('basicValidate', () => {
  it('accepts Markush wildcard atoms used as attachment points', () => {
    expect(basicValidate('*c1ccc(*)nc1')).toEqual({ valid: true })
  })
})
