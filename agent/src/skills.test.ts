import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readResearchSkill, researchSkills } from './skills.js'

test('registered research skills load and resource reads stay within the fixed allow-list', () => {
  assert.deepEqual(researchSkills.map(skill => skill.name), ['literature-search', 'patent-search'])
  const guide = readResearchSkill('literature-search')
  assert.equal(guide.version, '1.2.0')
  assert.match(guide.sha256, /^[a-f0-9]{64}$/)
  assert.throws(() => readResearchSkill('../../settings.json'), /Unknown research skill/)
  assert.throws(() => readResearchSkill('literature-search', '../settings.json'), /Unknown resource/)
  assert.throws(() => readResearchSkill('patent-search', 'citation-rules'), /Unknown resource/)
})
