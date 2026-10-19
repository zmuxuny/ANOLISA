import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { apply } from '../lib/index.js'

function statusTool() {
  const registered = []
  apply({
    tools: { register: (tool) => registered.push(tool) },
    logger: { info() {} },
  })
  assert.equal(registered.length, 1)
  assert.equal(registered[0].name, 'agentsight_status')
  return registered[0]
}

test('the canonical status value retains the package version and capabilities', async () => {
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
  assert.deepEqual(await statusTool().execute(), {
    plugin: 'agentsight', version: pkg.version, active: true, capabilities: ['status'],
  })
})

test('the renderer returns host content blocks from the value, not arguments', async () => {
  const tool = statusTool()
  const value = await tool.execute()
  const content = tool.output.render({ version: 'wrong-argument', active: false }, value)
  assert.ok(Array.isArray(content), 'dsh consumes a ContentBlock array')
  assert.deepEqual(content, [{ type: 'text', text: `AgentSight v${value.version} — active` }])
  assert.ok(content.some((block) => block.type === 'text'))
})

test('the renderer uses inactive and replacement version values faithfully', () => {
  const content = statusTool().output.render({}, {
    plugin: 'agentsight', version: 'fixture-version', active: false, capabilities: ['status'],
  })
  assert.deepEqual(content, [{ type: 'text', text: 'AgentSight vfixture-version — inactive' }])
})
