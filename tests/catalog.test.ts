import { test } from 'node:test'
import assert from 'node:assert/strict'
import { submissionUrl, filterPlugins, registry, type Plugin } from '../src/lib/catalog.ts'

test('submissions use fixed GitHub origin and filters return matching records', () => {
  assert.throws(() => submissionUrl('https://evil.example/owner/repo'))
  assert.throws(() => submissionUrl('https://github.com/owner/repo?token=secret'))
  assert.throws(() => submissionUrl('https://user:token@github.com/owner/repo'))
  assert.match(submissionUrl('https://github.com/owner/repo'), /labels=publish/)
  assert.equal(filterPlugins(registry.plugins, 'impossible-search-000', '', false, 'name').length, 0)
  assert.ok(filterPlugins(registry.plugins, '', '', true, 'name').every(plugin => plugin.status === 'verified'))
})

test('verified plugins are listed before unverified plugins', () => {
  const base = registry.plugins[0]
  assert.ok(base)
  const plugins = [
    { ...base, name: 'Alpha', status: 'unverified', stars: 100, publishedAt: '2026-10-17' },
    { ...base, name: 'Zulu', status: 'verified', stars: 1, publishedAt: '2026-01-01' },
  ] satisfies Plugin[]
  for (const sort of ['name', 'stars', 'recent']) {
    assert.deepEqual(filterPlugins(plugins, '', '', false, sort).map(plugin => plugin.name), ['Zulu', 'Alpha'])
  }
})
