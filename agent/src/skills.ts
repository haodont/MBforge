/** Fixed, read-only research skills loaded from this product's own directory. */
import { createHash } from 'node:crypto'
import { readFileSync, realpathSync, statSync } from 'node:fs'
import { isAbsolute, join, relative, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Type } from '@earendil-works/pi-ai'
import { defineTool, loadSkills, type Skill } from '@earendil-works/pi-coding-agent'

const skillsDirectory = fileURLToPath(new URL('../skills/', import.meta.url))
const definitions = {
  'literature-search': {
    version: '1.2.0',
    resources: {
      guide: 'SKILL.md',
      'biomedical-sources': 'references/biomedical-sources.md',
      'citation-rules': 'references/citation-rules.md',
    },
  },
  'patent-search': {
    version: '1.1.0',
    resources: {
      guide: 'SKILL.md',
      'identifiers-and-families': 'references/identifiers-and-families.md',
    },
  },
} as const

type SkillName = keyof typeof definitions
const skillNames = Object.keys(definitions) as SkillName[]
const maxSkillBytes = 32_000

function assertContained(root: string, path: string): string {
  const realRoot = realpathSync(root)
  const realPath = realpathSync(path)
  const relativePath = relative(realRoot, realPath)
  if (!relativePath || relativePath === '..' || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath)) {
    throw new Error('Research skill resource is outside its registered directory')
  }
  return realPath
}

function registeredSkillFile(name: SkillName): string {
  const root = realpathSync(skillsDirectory)
  const skillDirectory = assertContained(root, join(root, name))
  return assertContained(skillDirectory, join(skillDirectory, 'SKILL.md'))
}

function loadRegisteredSkills(): Skill[] {
  const root = realpathSync(skillsDirectory)
  const result = loadSkills({
    cwd: root,
    agentDir: root,
    skillPaths: skillNames.map(registeredSkillFile),
    includeDefaults: false,
  })
  if (result.diagnostics.length) {
    throw new Error('Could not load MBForge research skills: ' + result.diagnostics.map(item => item.message).join('; '))
  }
  const loaded = new Map(result.skills.map(skill => [skill.name, skill]))
  if (loaded.size !== skillNames.length || skillNames.some(name => !loaded.has(name))) {
    throw new Error('The MBForge research skill names do not match the fixed registry')
  }
  for (const name of skillNames) {
    const skill = loaded.get(name)
    if (!skill || assertContained(root, skill.filePath) !== registeredSkillFile(name)) {
      throw new Error('An MBForge research skill resolved outside its registered file')
    }
  }
  return skillNames.map(name => loaded.get(name)!)
}

export const researchSkills = loadRegisteredSkills()

export function researchSkillCatalog(): string {
  return researchSkills.map(skill => `- ${skill.name}: ${skill.description}`).join('\n')
}

export function readResearchSkill(name: string, resource = 'guide'): {
  skill: SkillName
  version: string
  resource: string
  sha256: string
  content: string
} {
  if (!Object.hasOwn(definitions, name)) throw new Error('Unknown research skill')
  const skillName = name as SkillName
  const definition = definitions[skillName]
  if (!Object.hasOwn(definition.resources, resource)) throw new Error('Unknown resource for this research skill')
  const relativeFile = definition.resources[resource as keyof typeof definition.resources]
  const skillDirectory = realpathSync(join(realpathSync(skillsDirectory), skillName))
  const path = assertContained(skillDirectory, join(skillDirectory, relativeFile))
  const size = statSync(path).size
  if (size > maxSkillBytes) throw new Error('Research skill resource exceeds the size limit')
  const content = readFileSync(path, 'utf8')
  const hashContent = content.replace(/\r\n?/g, '\n')
  return {
    skill: skillName,
    version: definition.version,
    resource,
    sha256: createHash('sha256').update(hashContent).digest('hex'),
    content,
  }
}

export const loadSkillTool = defineTool({
  name: 'load_skill',
  label: 'Load research skill',
  description: 'Load one registered MBForge research guide on demand. Omit resource for its guide. literature-search resources: biomedical-sources, citation-rules. Use search_papers for Europe PMC and search_structures for RCSB PDB when public research is enabled. patent-search resources: identifiers-and-families. References are loaded only when needed; arbitrary paths are not accepted.',
  parameters: Type.Object({
    name: Type.Union([Type.Literal('literature-search'), Type.Literal('patent-search')]),
    resource: Type.Optional(Type.Union([
      Type.Literal('guide'),
      Type.Literal('biomedical-sources'),
      Type.Literal('citation-rules'),
      Type.Literal('identifiers-and-families'),
    ])),
  }, { additionalProperties: false }),
  async execute(_id, params) {
    const payload = readResearchSkill(params.name, params.resource)
    return {
      content: [{ type: 'text' as const, text: JSON.stringify(payload) }],
      details: { skill: payload.skill, version: payload.version, resource: payload.resource, sha256: payload.sha256 },
    }
  },
})
