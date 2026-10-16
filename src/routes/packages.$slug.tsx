import { seo } from '../lib/seo'
import { createFileRoute, Link, notFound } from '@tanstack/react-router'
import { ArrowLeft, ArrowUpRight, BadgeCheck, ExternalLink } from 'lucide-react'
import { ReviewForm } from '../components/review-form'
import { CopyButton } from '../components/copy-button'
import { StatusBadge } from '../components/status-badge'
import { displayDate, registry, sourceUrl } from '../lib/catalog'

export const Route = createFileRoute('/packages/$slug')({
  loader: ({ params }) => {
    const plugin = registry.plugins.find(plugin => plugin.slug === params.slug)
    if (!plugin) throw notFound()
    return { plugin, history: registry.releases.filter(release => release.package === plugin.package) }
  },
  head: ({ loaderData }) => seo(`/packages/${loaderData?.plugin.slug || ''}`, `${loaderData?.plugin.name || 'Plugin'} — Omarchy plugin | Omachest`, loaderData ? `${loaderData.plugin.description} Inspect its exact source commit, scan results and review history on Omachest.` : 'Inspect Omarchy plugin source and review history.'),
  component: Package,
})

function Package() {
  const { plugin, history } = Route.useLoaderData()
  const repository = `https://github.com/${plugin.repository}`
  return <>
    <Link to="/" search={{ q: '', kind: '', checked: false, sort: 'name' }} className="back-link"><ArrowLeft size={15} aria-hidden="true" />All plugins</Link>
    <div className="package-heading"><div><p className="eyebrow"><bdi>{plugin.package}</bdi></p><h1>{plugin.name} <span className="version">v{plugin.version}</span></h1><p>{plugin.description}</p></div><StatusBadge status={plugin.status} /></div>
    <nav className="package-actions" aria-label="Plugin sections"><a className="button" href="#review-actions">Review this plugin ↓</a><a className="button" href="#security-evidence">Inspect scan ↓</a><a className="text-link" href="#report" onClick={() => { const report = document.getElementById('report'); if (report instanceof HTMLDetailsElement) report.open = true }}>Report a problem</a></nav>
    <div className="package-columns"><div className="package-content">
      <div className="section-title"><h2>Start with the source</h2><span>Version {plugin.version}</span></div>
      <p>Read the code and installation instructions at this exact commit.</p>
      <a href={sourceUrl(plugin)} className="button primary">Inspect source <ArrowUpRight size={17} aria-hidden="true" /></a>
      <div className="commit-box"><span className="eyebrow">Source commit</span><code>{plugin.commit}</code><CopyButton value={plugin.commit} label="Copy commit SHA" /></div>
      <p>The standard Omarchy install command follows upstream code and may install a different commit. Check the repository’s instructions before installing.</p>
      <div className="section-title"><h2>Release history</h2><span>{history.length} {history.length === 1 ? 'release' : 'releases'}</span></div>
      {history.length ? <div className="table-scroll"><table><caption className="sr-only">Published versions of {plugin.name}</caption><thead><tr><th scope="col">Version</th><th scope="col">Published</th><th scope="col">Publisher</th><th scope="col">Record</th></tr></thead><tbody>{history.map(release => <tr key={release.commit}><td>v{release.version}</td><td>{displayDate(release.publishedAt)}</td><td><bdi>{release.publisher || 'Upstream monitor'}</bdi></td><td><a href={release.receipt} aria-label={`View receipt for version ${release.version}`}>Receipt ↗</a></td></tr>)}</tbody></table></div> : <p>No scanned versions are recorded yet. This discovery listing is unverified.</p>}
      {plugin.changelog && <details className="digest-details"><summary>Latest upstream release notes</summary><pre>{plugin.changelog}</pre><a href={plugin.releaseUrl}>Full release notes ↗</a></details>}
      <div className="section-title"><h2>What was checked</h2></div>
      <div className="notice"><BadgeCheck size={20} aria-hidden="true" /><p>{plugin.scan?.validation === 'passed' ? 'Manifest structure, declared files, QML parsing, repository identity and bounded source analysis passed at this commit.' : 'This listing comes from a public repository manifest. It has not passed this registry’s publication checks.'}</p></div>
      <h2>{plugin.submissionStatus}</h2><p>{({ 'PENDING REVIEW': 'Waiting for human review. No verification has been granted.', APPROVED: 'This exact commit was reviewed according to the registry checklist.', REJECTED: 'A reviewer rejected this commit. Read the decision below.', 'CHANGES REQUESTED': 'A reviewer requested changes before approval. Read the notes below.', 'REVIEW REQUIRED': 'Upstream code or trust signals changed. The current state needs another review.', REVOKED: 'This commit was revoked due to a security or policy issue. Read the reason and recommendation below.' } as Record<string, string>)[plugin.submissionStatus]}</p>
      {plugin.verification && <div className="notice"><p>Verified version {plugin.verification.version}: <code>{plugin.verification.commit}</code><br />Reviewed by {plugin.verification.reviewer} on {displayDate(plugin.verification.timestamp)}.{plugin.verification.commit !== plugin.commit && ' New commit detected. The current upstream commit has not been reviewed.'}</p></div>}
      <div id="security-evidence" className="section-title"><h2>Security capabilities</h2><span>Last scan: {plugin.scan ? displayDate(plugin.publishedAt) : 'Not scanned'}</span></div>
      <p>Automated security analysis is not a guarantee that a plugin is safe. “No match” means the scanner did not recognize a pattern; it is not proof of absence.</p>
      {plugin.capabilityChanges?.length ? <div className="notice"><p>Security capability change detected: {plugin.capabilityChanges.join(', ')}. Human review required.</p></div> : null}
      {plugin.scan ? Object.entries(plugin.scan.capabilities).map(([capability, evidence]) => <details className="digest-details" key={capability}><summary>{capability} · {evidence.length ? `${plugin.scan?.counts?.[capability] || evidence.length} matches` : 'No match'}</summary>{evidence.map((item, index) => <p key={index}><a href={`${sourceUrl(plugin)}/${item.file.split('/').map(encodeURIComponent).join('/')}#L${item.line}`}>{item.file}:{item.line} ↗</a><code className="evidence">{item.evidence}</code></p>)}</details>) : <p>Capability analysis has not completed for this snapshot.</p>}
      {plugin.scan && <details className="digest-details"><summary>Automated validation details</summary><p>{plugin.scan.method}</p><ul>{plugin.scan.qml.map(file => <li key={file.file}>{file.file}: parsed, {file.warnings} diagnostics. {file.note}</li>)}</ul></details>}
      {plugin.manifest && <details className="digest-details"><summary>Manifest at this commit</summary><pre>{JSON.stringify(plugin.manifest, null, 2)}</pre></details>}
      <h2>Review history</h2>{plugin.reviews?.length ? plugin.reviews.map((review, index) => <article className="notice" key={index}><div><strong>{review.action.toUpperCase()} · v{review.version}</strong><p>{review.reviewer} · {displayDate(review.timestamp)}<br /><code>{review.commit}</code></p><p>{review.notes}</p>{review.recommendation && <p>Security advisory recommendation: {review.recommendation}</p>}<a href={review.receipt}>Audit record ↗</a></div></article>) : <p>No human review recorded.</p>}
      {plugin.reports?.length ? <><h2>Reports awaiting moderation</h2>{plugin.reports.map((report, index) => <p key={index}>{report.reason} · {displayDate(report.timestamp)} — {report.notes} {report.rescan ? 'Rescan completed.' : report.rescanError ? 'Rescan failed.' : ''} {report.receipt && <a href={report.receipt}>Record ↗</a>}</p>)}</> : null}
      {plugin.trustEvents?.map((event, index) => <p role="status" key={index}>{event.notes || `Repository state changed: ${JSON.stringify(event.state)}`} · {displayDate(event.timestamp)}</p>)}
      {plugin.compareUrl && <details className="digest-details"><summary>Changed files since the previous scan</summary><a href={plugin.compareUrl}>Inspect complete code diff ↗</a><ul>{plugin.changedFiles?.map(file => <li key={file}>{file}</li>)}</ul></details>}
      <ReviewForm plugin={plugin} />
      {plugin.warnings.length ? <ul className="warnings">{plugin.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul> : null}
      <p>These checks do not include runtime testing or a full dependency audit. Plugins run with your user permissions. <Link to="/security" className="text-link">Read the verification policy</Link>.</p>
      {plugin.manifestSha256 ? <details className="digest-details"><summary>Manifest SHA-256 digest</summary><pre>{plugin.manifestSha256}</pre></details> : null}
    </div><aside className="package-facts"><h2>Package details</h2><dl><dt>Author</dt><dd><bdi>{plugin.author}</bdi></dd><dt>Repository owner</dt><dd><bdi>{plugin.repository.split('/')[0]}</bdi></dd><dt>Plugin ID</dt><dd><bdi>{plugin.id}</bdi></dd><dt>License</dt><dd>{plugin.license}</dd><dt>GitHub stars · snapshot</dt><dd>{plugin.stars}</dd><dt>Repository created</dt><dd>{displayDate(plugin.repositoryCreatedAt)}</dd><dt>Downloads / installations</dt><dd>Not measured</dd></dl>
      <a href={repository}>Repository & history <ExternalLink size={13} aria-hidden="true" /></a><a href={`${repository}/security/advisories`}>Security advisories <ExternalLink size={13} aria-hidden="true" /></a><a href={`${repository}/network/dependencies`}>Dependency graph <ExternalLink size={13} aria-hidden="true" /></a><Link to="/publish" search={{ repository: plugin.repository, path: plugin.path }}>Publish an update <ArrowUpRight size={14} aria-hidden="true" /></Link>
    </aside></div>
  </>
}
