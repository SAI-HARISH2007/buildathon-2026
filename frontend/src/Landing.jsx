import { useEffect, useRef, useState } from 'react'
import './landing.css'

function Reveal({ children, className = '', delay = 0 }) {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { el.classList.add('in'); io.disconnect() }
    }, { threshold: 0.25 })
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return <div ref={ref} className={`reveal ${className}`} style={{ transitionDelay: `${delay}ms` }}>{children}</div>
}

function CountUp({ to, prefix = '', suffix = '', duration = 1400 }) {
  const [val, setVal] = useState(0)
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return
      io.disconnect()
      const t0 = performance.now()
      const tick = (t) => {
        const p = Math.min((t - t0) / duration, 1)
        setVal(Math.round(to * (1 - Math.pow(1 - p, 3))))
        if (p < 1) requestAnimationFrame(tick)
      }
      requestAnimationFrame(tick)
    }, { threshold: 0.5 })
    io.observe(el)
    return () => io.disconnect()
  }, [to, duration])
  return <span ref={ref}>{prefix}{val.toLocaleString('en-IN')}{suffix}</span>
}

const CATEGORIES = [
  ['Transient bank issue', 'retry with backoff'],
  ['Insufficient funds', 'retry after payday'],
  ['Customer fumble', 'fresh link, fast'],
  ['Dead instrument', 'offer another method'],
  ['Limit exceeded', 'retry post-reset'],
  ['Ambiguous', 'AI decides, bounded'],
  ['Risk / compliance', 'humans only'],
  ['Merchant config', 'alert the merchant'],
]

export default function Landing() {
  const heroCard = useRef(null)
  const [scrollY, setScrollY] = useState(0)

  useEffect(() => {
    const onScroll = () => setScrollY(window.scrollY)
    const onMove = (e) => {
      const el = heroCard.current
      if (!el) return
      const r = el.getBoundingClientRect()
      const dx = (e.clientX - r.left - r.width / 2) / r.width
      const dy = (e.clientY - r.top - r.height / 2) / r.height
      el.style.transform = `perspective(1100px) rotateY(${dx * 10}deg) rotateX(${-dy * 8}deg) translateZ(0)`
    }
    const onLeave = () => {
      if (heroCard.current)
        heroCard.current.style.transform = 'perspective(1100px) rotateY(-8deg) rotateX(4deg)'
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    const hero = document.querySelector('.hero')
    hero?.addEventListener('mousemove', onMove)
    hero?.addEventListener('mouseleave', onLeave)
    return () => {
      window.removeEventListener('scroll', onScroll)
      hero?.removeEventListener('mousemove', onMove)
      hero?.removeEventListener('mouseleave', onLeave)
    }
  }, [])

  return (
    <div className="landing">
      <div className="orb orb-a" style={{ transform: `translateY(${scrollY * 0.18}px)` }} />
      <div className="orb orb-b" style={{ transform: `translateY(${scrollY * -0.12}px)` }} />

      <nav className="lnav">
        <span className="lbrand">Reclaim</span>
        <a className="lnav-cta" href="#/dashboard">Open dashboard</a>
      </nav>

      <header className="hero">
        <div className="hero-copy">
          <p className="eyebrow">AI revenue recovery · built on Razorpay</p>
          <h1>Failed payments aren&apos;t lost.<br /><em>They&apos;re waiting.</em></h1>
          <p className="lede">
            Reclaim reads every failed payment, works out <strong>why</strong> it failed,
            and runs the right recovery play — rules where correctness is knowable,
            AI where judgment is needed, hard safety bounds everywhere.
          </p>
          <div className="hero-ctas">
            <a className="cta" href="#/dashboard">See it recover revenue →</a>
            <a className="cta ghost" href="https://github.com/SAI-HARISH2007/buildathon-2026" target="_blank" rel="noreferrer">Read the code</a>
          </div>
        </div>
        <div className="hero-stage">
          <div className="tilt-card" ref={heroCard}>
            <div className="tc-head"><span className="tc-dot" /><span className="tc-dot" /><span className="tc-dot" /></div>
            <div className="tc-label">Revenue recovered</div>
            <div className="tc-value">₹1,70,557</div>
            <div className="tc-sub">of ₹2,69,425 failed · 5 simulated days</div>
            <div className="tc-bar"><span style={{ width: '65%' }} /></div>
            <div className="tc-row"><span>Recovery rate</span><b>65%</b></div>
            <div className="tc-row"><span>Quarantined for humans</span><b>10</b></div>
          </div>
        </div>
      </header>

      <section className="band">
        <Reveal><h2>It knows <em>why</em> payments fail.</h2></Reveal>
        <Reveal delay={100}>
          <p className="band-sub">
            Razorpay documents <b>114 failure reasons</b>. Reclaim maps every one of them into
            eight recovery categories with a deterministic rule table — auditable, testable,
            and incapable of hallucinating a retry against a compliance block.
          </p>
        </Reveal>
        <div className="cat-grid">
          {CATEGORIES.map(([name, play], i) => (
            <Reveal key={name} delay={i * 70}>
              <div className="cat-card"><b>{name}</b><span>{play}</span></div>
            </Reveal>
          ))}
        </div>
      </section>

      <section className="band split">
        <Reveal className="half">
          <div className="pillar rule">
            <div className="pill">RULES</div>
            <h3>Where correctness is knowable</h3>
            <p>Classification, retry caps, cool-downs, no-retry classes — enforced in code,
               not prompts. The LLM proposes; the rules dispose.</p>
          </div>
        </Reveal>
        <Reveal className="half" delay={150}>
          <div className="pillar llm">
            <div className="pill blue">AI</div>
            <h3>Where judgment is needed</h3>
            <p>Opaque declines the bank explains to nobody: the model weighs amount, method
               and timing, picks a bounded play, drafts the customer message — and is
               <b> eval-guarded</b>: 12 labeled cases, 4 checks, every regression caught.</p>
          </div>
        </Reveal>
      </section>

      <section className="band stats">
        <Reveal><h2>The demo batch, recovered.</h2></Reveal>
        <div className="stat-row">
          <Reveal delay={0}><div className="big-stat"><CountUp to={65} suffix="%" /><span className="lbl">recovery rate</span></div></Reveal>
          <Reveal delay={120}><div className="big-stat"><CountUp to={170557} prefix="₹" /><span className="lbl">revenue recovered</span></div></Reveal>
          <Reveal delay={240}><div className="big-stat"><CountUp to={114} /><span className="lbl">failure reasons handled</span></div></Reveal>
          <Reveal delay={360}><div className="big-stat"><CountUp to={1} /><span className="lbl">LLM call site — eval-guarded</span></div></Reveal>
        </div>
        <Reveal delay={200}>
          <a className="cta big" href="#/dashboard">Open the live dashboard →</a>
        </Reveal>
      </section>

      <footer className="lfoot">
        Built for the Razorpay AI Buildathon · Track 03: AI Revenue Recovery ·
        every decision audited, every bug logged
      </footer>
    </div>
  )
}
