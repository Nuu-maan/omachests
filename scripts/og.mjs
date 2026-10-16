import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { Resvg } from '@resvg/resvg-js'
import satori from 'satori'

const ROOT = new URL('../', import.meta.url)
const OUT = new URL('public/og/', ROOT)
const font = path => readFile(new URL(`node_modules/@fontsource/${path}`, ROOT))
const fonts = [
  { name: 'Mono', weight: 400, data: await font('jetbrains-mono/files/jetbrains-mono-latin-400-normal.woff') },
  { name: 'Mono', weight: 600, data: await font('jetbrains-mono/files/jetbrains-mono-latin-600-normal.woff') },
  { name: 'Pixel', weight: 700, data: await font('silkscreen/files/silkscreen-latin-700-normal.woff') },
]
const color = { page: '#0e0f0f', line: '#343939', control: '#747c7c', text: '#f0f0eb', secondary: '#b1b6b3', positive: '#afd39c' }
const labels = { verified: 'Verified', unverified: 'Unverified', 'review-required': 'Review required', revoked: 'Revoked' }

const h = (type, style, ...children) => ({ type, props: { style: { display: 'flex', ...style }, children } })
const text = (value, style) => h('div', { fontFamily: 'Mono', color: color.secondary, ...style }, value)
function clip(value, limit) {
  if (value.length <= limit) return value
  const space = value.lastIndexOf(' ', limit - 1)
  return value.slice(0, space > 0 ? space : limit).replace(/[,;:.]$/, '') + '…'
}
if (clip('x'.repeat(50), 40) !== 'x'.repeat(40) + '…') throw new Error('Text clipping self-check failed')
const pixels = Array.from({ length: 24 }, (_, i) => h('div', {
  position: 'absolute', width: 10, height: 10, backgroundColor: color.text,
  left: `${(i * 37) % 100}%`, top: `${(i * 23) % 95}%`, opacity: (i % 3 + 1) * 0.05,
}))

function frame(kicker, title, subtitle, footer, badge) {
  return h('div', { width: 1200, height: 630, backgroundColor: color.page, padding: 64, flexDirection: 'column', justifyContent: 'space-between', position: 'relative' },
    ...pixels,
    h('div', { justifyContent: 'space-between', alignItems: 'center' },
      h('div', { alignItems: 'center', gap: 14 },
        h('div', { width: 10, height: 10, backgroundColor: color.positive }),
        text(kicker, { fontSize: 24 })),
      badge && text(badge.label, { fontSize: 22, fontWeight: 600, color: badge.color, border: `1px solid ${badge.color}`, padding: '8px 18px' })),
    h('div', { flexDirection: 'column', gap: 26 },
      text(clip(title, 40), { fontFamily: 'Pixel', fontWeight: 700, fontSize: 66, lineHeight: 1.15, color: color.text, letterSpacing: -2 }),
      text(clip(subtitle, 170), { fontSize: 28, lineHeight: 1.5, maxWidth: 1000 })),
    h('div', { justifyContent: 'space-between', alignItems: 'center', borderTop: `1px solid ${color.line}`, paddingTop: 28 },
      text(footer, { fontSize: 24, color: color.text }),
      text('omachests.com', { fontSize: 24 })))
}

async function render(name, element) {
  const svg = await satori(element, { width: 1200, height: 630, fonts })
  const png = new Resvg(svg, { fitTo: { mode: 'width', value: 1200 } }).render().asPng()
  if (png.length < 1000) throw new Error(`Suspiciously small image for ${name}`)
  await writeFile(new URL(`${name}.png`, OUT), png)
}

const registry = JSON.parse(await readFile(new URL('public/registry.json', ROOT), 'utf8'))
const verified = registry.plugins.filter(p => p.status === 'verified').length
const queue = registry.plugins.length - verified
const kind = value => (value || 'plugin').replace('bar-widget', 'bar widget').replace(/^./, c => c.toUpperCase())
const pages = {
  home: ['Find your next plugin.', 'Community plugins for Omarchy. Inspect exact source commits and human review notes before you install.', `${registry.plugins.length} plugins / ${verified} verified`],
  publish: ['Submit your plugin.', 'One repository link. We read the manifest, inspect the source, and queue the exact commit for human review.', 'Push updates as usual. We rescan every new commit.'],
  review: ['A clear path to verification.', 'Inspect a plugin’s source and scan, then record your decision. Reports and changed code come first.', `${queue} plugins awaiting review`],
  activity: ['Every release leaves a trail.', 'Scanned commits and public records for every plugin release. Automated scans do not grant verification.', `${registry.releases.length} scanned releases`],
  security: ['Trust starts with evidence.', 'What the labels mean, what they miss, and how to inspect a plugin yourself before installing it.', 'Verification is tied to one exact commit'],
}

await mkdir(OUT, { recursive: true })
for (const [name, [title, subtitle, footer]] of Object.entries(pages)) {
  await render(name, frame('omachest / plugins', title, subtitle, footer))
}
for (const plugin of registry.plugins) {
  const badge = { label: labels[plugin.status], color: plugin.status === 'verified' ? color.positive : color.secondary }
  const footer = `@${plugin.repository.split('/')[0]}  /  v${plugin.version}  /  ${kind(plugin.kinds[0])}  /  ${plugin.stars} stars`
  await render(plugin.slug, frame('omachest / plugins', plugin.name, plugin.description, footer, badge))
}
console.log(`Rendered ${Object.keys(pages).length + registry.plugins.length} social images.`)
