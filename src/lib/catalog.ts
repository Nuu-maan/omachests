import snapshot from '../../public/registry.json' with { type: 'json' }

export type Scan = { counts?: Record<string, number>; validation: string; method: string; capabilities: Record<string, { file: string; line: number; evidence: string }[]>; qml: { file: string; warnings: number; note: string }[] }
export type Review = { action: string; commit: string; version: string; reviewer: string; timestamp: string; notes: string; recommendation?: string; receipt?: string }

export type Plugin = {
  package: string
  repository: string
  repositoryId: number
  path: string
  commit: string
  id: string
  name: string
  description: string
  author: string
  license: string
  version: string
  kinds: string[]
  stars: number
  forks: number
  repositoryCreatedAt: string
  status: 'verified' | 'unverified' | 'review-required' | 'revoked'
  submissionStatus: string
  trustEvents?: { notes?: string; timestamp: string; state?: { repository: string; archived: boolean; disabled: boolean } }[]
  changelog?: string
  releaseUrl?: string
  changedFiles?: string[]
  compareUrl?: string
  scan?: Scan
  scanDigest?: string
  manifest?: Record<string, unknown>
  reviews?: Review[]
  verification?: Review | null
  capabilityChanges?: string[]
  reports?: { reason: string; notes: string; timestamp: string; receipt?: string }[]
  publishedAt: string | null
  importedAt?: string
  publisher: string | null
  warnings: string[]
  slug: string
  receipt?: string
  manifestSha256?: string
}

export const registry = snapshot as { schemaVersion: number; plugins: Plugin[]; releases: Plugin[] }
export const repositoryUrl = 'https://github.com/Nuu-maan/omachests'
export const kinds = [
  { value: '', label: 'All plugins' },
  { value: 'bar', label: 'Bars' },
  { value: 'bar-widget', label: 'Bar widgets' },
  { value: 'panel', label: 'Panels' },
  { value: 'overlay', label: 'Overlays' },
  { value: 'menu', label: 'Menus' },
  { value: 'service', label: 'Services' },
] as const

export function filterPlugins(plugins: Plugin[], query: string, kind: string, checked: boolean, sort: string): Plugin[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  return plugins.filter(plugin => {
    const text = [plugin.name, plugin.description, plugin.repository, plugin.id, ...plugin.kinds].join(' ').toLowerCase()
    return words.every(word => text.includes(word)) && (!kind || plugin.kinds.includes(kind)) && (!checked || plugin.status === 'verified')
  }).sort((a, b) => {
    const verificationOrder = Number(b.status === 'verified') - Number(a.status === 'verified')
    if (verificationOrder) return verificationOrder
    if (sort === 'stars') return b.stars - a.stars || a.name.localeCompare(b.name)
    if (sort === 'recent') return (b.publishedAt || b.importedAt || '').localeCompare(a.publishedAt || a.importedAt || '')
    return a.name.localeCompare(b.name)
  })
}

export function sourceUrl(plugin: Plugin): string {
  return `https://github.com/${plugin.repository}/tree/${plugin.commit}${plugin.path ? '/' + plugin.path.split('/').map(encodeURIComponent).join('/') : ''}`
}

export function displayDate(value: string | null | undefined): string {
  if (!value) return 'Not published'
  return new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(value))
}

export function issueUrl(label: string, title: string, value: Record<string, unknown>): string {
  const body = '```json\n' + JSON.stringify(value, null, 2) + '\n```'
  return `${repositoryUrl}/issues/new?${new URLSearchParams({ title, labels: label, body })}`
}

export function submissionUrl(repository: string, commit = '', path = ''): string {
  const parsed = new URL(repository.startsWith('https://') ? repository : `https://github.com/${repository}`)
  if (parsed.origin !== 'https://github.com' || parsed.username || parsed.password || parsed.search || parsed.hash || !/^\/[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9_.-]{1,100}\/?$/.test(parsed.pathname) || ['.', '..'].includes(parsed.pathname.split('/')[2])) throw new Error('Enter a GitHub repository URL, such as https://github.com/owner/plugin.')
  if (commit && !/^[a-f0-9]{40}$/.test(commit)) throw new Error('Use a full 40-character commit SHA.')
  if (path && (path.length > 200 || !/^[A-Za-z0-9_. /-]+$/.test(path) || path.split('/').some(part => ['', '.', '..'].includes(part)))) throw new Error('Use a relative directory without . or .. segments.')
  return issueUrl('publish', `Submit: ${parsed.pathname.slice(1)}`, { repository: parsed.href, ...(commit ? { commit } : {}), path })
}
