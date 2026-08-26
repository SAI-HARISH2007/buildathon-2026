import { useCallback, useEffect, useState } from 'react'

const inr = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })
const rupees = (paise) => `₹${inr.format(Math.round(paise / 100))}`

const STATUS_META = {
  recovered:      { label: 'Recovered',      tone: 'good',     icon: '✓' },
  scheduled:      { label: 'Scheduled',      tone: 'warning',  icon: '◷' },
  failed:         { label: 'Failed',         tone: 'serious',  icon: '✕' },
  manual_review:  { label: 'Manual review',  tone: 'serious',  icon: '⚑' },
  merchant_alert: { label: 'Merchant alert', tone: 'serious',  icon: '⚠' },
  abandoned:      { label: 'Abandoned',      tone: 'critical', icon: '⊘' },
  dismissed:      { label: 'Dismissed',      tone: 'critical', icon: '—' },
}

const CATEGORY_LABELS = {
  transient: 'Transient bank issue',
  insufficient_funds: 'Insufficient funds',
  customer_fumble: 'Customer fumble',
  instrument_invalid: 'Dead instrument',
  limit_exceeded: 'Limit exceeded',
  ambiguous: 'Ambiguous (AI-triaged)',
  do_not_retry: 'Do not retry',
  merchant_config: 'Merchant config',
}

async function api(path, opts) {
  const res = await fetch(`/api${path}`, opts)
  if (!res.ok) throw new Error(`${path}: ${res.status}`)
  return res.json()
}
const post = (path, body) =>
  api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: body ? JSON.stringify(body) : undefined })

function StatusBadge({ status }) {
  const m = STATUS_META[status] ?? { label: status, tone: 'warning', icon: '·' }
  return <span className={`badge badge-${m.tone}`}><span aria-hidden>{m.icon}</span>{m.label}</span>
}

function StatTiles({ stats }) {
  const inFlight = stats.by_status?.scheduled?.count ?? 0
  const needsHuman = (stats.by_status?.manual_review?.count ?? 0) +
                     (stats.by_status?.merchant_alert?.count ?? 0)
  return (
    <section className="tiles">
      <div className="tile tile-hero">
        <div className="tile-label">Revenue recovered</div>
        <div className="tile-value hero">{rupees(stats.recovered_amount)}</div>
        <div className="tile-sub">of {rupees(stats.total_amount)} failed</div>
      </div>
      <div className="tile">
        <div className="tile-label">Recovery rate</div>
        <div className="tile-value">{(stats.recovery_rate * 100).toFixed(1)}%</div>
        <div className="tile-sub">{stats.recovered} of {stats.total_failed} payments</div>
      </div>
      <div className="tile">
        <div className="tile-label">In flight</div>
        <div className="tile-value">{inFlight}</div>
        <div className="tile-sub">retries scheduled</div>
      </div>
      <div className="tile">
        <div className="tile-label">Needs a human</div>
        <div className="tile-value">{needsHuman}</div>
        <div className="tile-sub">risk, compliance &amp; config</div>
      </div>
    </section>
  )
}

function CategoryBars({ stats }) {
  const cats = Object.entries(stats.by_category ?? {})
  if (!cats.length) return null
  const max = Math.max(...cats.map(([, v]) => v.count))
  return (
    <section className="panel">
      <h2>Failures by cause <span className="legend">
        <span className="key key-fill" /> recovered
        <span className="key key-track" /> total
      </span></h2>
      <div className="cat-bars">
        {cats.sort((a, b) => b[1].count - a[1].count).map(([cat, v]) => (
          <div className="cat-row" key={cat}
               title={`${CATEGORY_LABELS[cat] ?? cat}: ${v.recovered} recovered of ${v.count}`}>
            <span className="cat-name">{CATEGORY_LABELS[cat] ?? cat}</span>
            <span className="cat-bar">
              <span className="cat-track" style={{ width: `${(v.count / max) * 100}%` }}>
                <span className="cat-fill" style={{ width: `${v.count ? (v.recovered / v.count) * 100 : 0}%` }} />
              </span>
            </span>
            <span className="cat-num">{v.recovered}/{v.count}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

function Timeline({ payment, onReview, busy }) {
  if (!payment) return null
  const needsReview = payment.status === 'manual_review' || payment.status === 'merchant_alert'
  return (
    <aside className="drawer">
      <h2>{payment.payment_id}</h2>
      <p className="drawer-sub">
        {payment.customer_name} · {payment.method.toUpperCase()} · {rupees(payment.amount)} ·{' '}
        <StatusBadge status={payment.status} />
      </p>
      {needsReview && (
        <div className="review-actions">
          <span className="review-hint">The agent won't act on this without a human.</span>
          <button disabled={busy} onClick={() => onReview('approve_retry')}>✓ Approve one retry</button>
          <button disabled={busy} onClick={() => onReview('dismiss')}>— Dismiss</button>
        </div>
      )}
      <ol className="timeline">
        {payment.timeline.map((a, i) => {
          const detail = a.detail ? JSON.parse(a.detail) : {}
          return (
            <li key={i} className={`tl tl-${a.source}`}>
              <div className="tl-head">
                <span className="tl-kind">{a.kind.replaceAll('_', ' ')}</span>
                <span className={`tl-source tl-source-${a.source}`}>{a.source}</span>
                <span className="tl-at">{a.at.replace('T', ' ')}</span>
              </div>
              {a.rationale && <div className="tl-why">{a.rationale}</div>}
              {detail.message && <div className="tl-msg">“{detail.message}”</div>}
              {detail.short_url && <div className="tl-why">link: {detail.short_url} ({detail.mode})</div>}
            </li>
          )
        })}
      </ol>
    </aside>
  )
}

export default function App() {
  const [stats, setStats] = useState(null)
  const [clock, setClock] = useState('—')
  const [payments, setPayments] = useState([])
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')

  const refresh = useCallback(async (statusFilter = filter) => {
    const [s, c, p] = await Promise.all([
      api('/stats'), api('/clock'),
      api(`/payments${statusFilter ? `?status=${statusFilter}` : ''}`),
    ])
    setStats(s); setClock(c.now.replace('T', '  ')); setPayments(p)
  }, [filter])

  useEffect(() => { refresh().catch(console.error) }, [refresh])

  const act = async (fn, label) => {
    setBusy(true)
    try {
      const out = await fn()
      if (label) setToast(`${label}${out.retries_executed != null ? ` — ${out.retries_executed} retries ran` : ''}`)
      await refresh()
      if (selected) setSelected(await api(`/payments/${selected.payment_id}`))
    } catch (e) { setToast(String(e)) }
    finally { setBusy(false); setTimeout(() => setToast(''), 4000) }
  }

  return (
    <div className="page">
      <header>
        <div className="brand">Reclaim <span className="brand-sub">failed-payment recovery agent</span></div>
        <div className="clock" title="Simulated time — recovery plays span days, so the demo clock fast-forwards">
          <span className="clock-label">sim clock</span> {clock}
        </div>
      </header>

      <div className="controls">
        <button disabled={busy} onClick={() => act(() => post('/reset').then(() => post('/ingest/demo')), 'Fresh batch ingested')}>
          ⟳ Reset + ingest demo batch
        </button>
        <span className="control-sep">fast-forward:</span>
        {[['10 min', 10], ['1 hour', 60], ['6 hours', 360], ['1 day', 1440], ['2 days', 2880]].map(([label, minutes]) => (
          <button key={minutes} disabled={busy}
                  onClick={() => act(() => post('/clock/advance', { minutes }), `+${label}`)}>
            +{label}
          </button>
        ))}
        {toast && <span className="toast">{toast}</span>}
      </div>

      {stats && stats.total_failed > 0 ? (
        <>
          <StatTiles stats={stats} />
          <div className="columns">
            <div className="col-main">
              <CategoryBars stats={stats} />
              <section className="panel">
                <h2>Payments
                  <select value={filter} onChange={(e) => { setFilter(e.target.value); }}>
                    <option value="">all statuses</option>
                    {Object.keys(STATUS_META).map((s) => <option key={s} value={s}>{STATUS_META[s].label}</option>)}
                  </select>
                </h2>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>Payment</th><th>Customer</th><th>Method</th><th>Failure reason</th>
                          <th className="num">Amount</th><th>Status</th><th className="num">Attempts</th></tr>
                    </thead>
                    <tbody>
                      {payments.map((p) => (
                        <tr key={p.payment_id}
                            className={selected?.payment_id === p.payment_id ? 'sel' : ''}
                            onClick={() => api(`/payments/${p.payment_id}`).then(setSelected)}>
                          <td className="mono">{p.payment_id.slice(4, 14)}</td>
                          <td>{p.customer_name}</td>
                          <td>{p.method.toUpperCase()}</td>
                          <td className="mono dim reason" title={p.failure_reason}>{p.failure_reason}</td>
                          <td className="num">{rupees(p.amount)}</td>
                          <td><StatusBadge status={p.status} /></td>
                          <td className="num">{p.attempts}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
            <Timeline payment={selected} busy={busy}
                      onReview={(action) => act(() => post(`/payments/${selected.payment_id}/review`, { action }),
                                                action === 'dismiss' ? 'Dismissed' : 'Retry approved')} />
          </div>
        </>
      ) : (
        <section className="empty">
          <p>No payments yet. Hit <strong>Reset + ingest demo batch</strong> to feed the agent
             200 synthetic failed payments, then fast-forward the clock and watch it recover revenue.</p>
        </section>
      )}
    </div>
  )
}
