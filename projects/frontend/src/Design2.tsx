import { useEffect, useRef, useState } from 'react'

const VIDEO = 'https://pub-9660dda224dc4727bc1eadab5cf0a535.r2.dev/ascii-magic-7.mp4'
const G = '#00ff88'
const B = '#0099ff'

type Design2Props = {
  startUrl: string
  loginUrl: string
}

function Cursor() {
  const [visible, setVisible] = useState(true)

  useEffect(() => {
    const timer = window.setInterval(() => setVisible((value) => !value), 530)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <span
      aria-hidden="true"
      style={{ display: 'inline-block', width: 8, height: '1em', background: visible ? G : 'transparent', verticalAlign: 'middle', marginLeft: 2 }}
    />
  )
}

function useTypewriter(text: string, speed = 28) {
  const [displayed, setDisplayed] = useState('')
  const [done, setDone] = useState(false)
  const elementRef = useRef<HTMLDivElement>(null)
  const started = useRef(false)

  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !started.current) {
        started.current = true
        let index = 0
        const timer = window.setInterval(() => {
          index += 1
          setDisplayed(text.slice(0, index))
          if (index >= text.length) {
            setDone(true)
            window.clearInterval(timer)
          }
        }, speed)
      }
    }, { threshold: 0.2 })

    if (elementRef.current) observer.observe(elementRef.current)
    return () => observer.disconnect()
  }, [text, speed])

  return { displayed, done, ref: elementRef }
}

function ScanLines() {
  return (
    <div
      aria-hidden="true"
      className="d2-scanlines"
      style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 2,
        backgroundImage: 'repeating-linear-gradient(0deg, transparent 0px, transparent 2px, rgba(0,0,0,0.35) 2px, rgba(0,0,0,0.35) 4px)',
        backgroundSize: '100% 4px',
      }}
    />
  )
}

function Nav({ startUrl }: Design2Props) {
  const timestamp = new Date().toISOString().slice(0, 19).replace('T', ' ')

  return (
    <nav className="d2-nav" style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
      background: 'rgba(0,6,0,0.95)', backdropFilter: 'blur(8px)',
      borderBottom: '1px solid rgba(0,255,136,0.15)',
      fontFamily: "'JetBrains Mono', monospace", padding: '0 40px',
      display: 'flex', alignItems: 'center', height: 52,
    }}>
      <span style={{ color: G, marginRight: 8 }}>▌</span>
      <span style={{ color: G, fontWeight: 700, fontSize: 14, letterSpacing: '0.05em' }}>PROJIVO</span>
      <span style={{ color: '#223322', marginLeft: 12, fontSize: 12 }}>v2.4.1</span>
      <div className="d2-nav-links" style={{ flex: 1, display: 'flex', justifyContent: 'center', gap: 32 }}>
        {[
          ['--manifesto', '#manifesto'],
          ['--features', '#features'],
          ['--blog', '#footer'],
        ].map(([label, href]) => (
          <a key={label} href={href} style={{ color: '#334455', fontSize: 12, textDecoration: 'none', letterSpacing: '0.06em', transition: 'color 0.2s' }}
            onMouseEnter={(event) => { event.currentTarget.style.color = G }}
            onMouseLeave={(event) => { event.currentTarget.style.color = '#334455' }}>{label}</a>
        ))}
      </div>
      <span className="d2-clock" style={{ color: '#334455', fontSize: 11, marginRight: 20 }}>{timestamp}</span>
      <a href={startUrl} style={{ background: 'transparent', color: G, border: `1px solid ${G}`, padding: '5px 14px', fontSize: 12, letterSpacing: '0.08em', textDecoration: 'none', fontFamily: 'inherit' }}>
        $ START
      </a>
    </nav>
  )
}

function Hero({ startUrl, loginUrl }: Pick<Design2Props, 'startUrl' | 'loginUrl'>) {
  const { displayed, done, ref } = useTypewriter('2 WEEKS OF PLANNING\nDONE IN 2 MINUTES', 40)

  return (
    <section id="manifesto" className="d2-section d2-hero" style={{ position: 'relative', minHeight: '100vh', overflow: 'hidden', background: '#000600', display: 'flex', alignItems: 'center' }}>
      <video src={VIDEO} autoPlay muted loop playsInline aria-hidden="true" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', opacity: 0.35, filter: 'hue-rotate(100deg) saturate(2)' }} />
      <ScanLines />
      <div aria-hidden="true" style={{ position: 'absolute', inset: 0, background: 'linear-gradient(to bottom, rgba(0,6,0,0.65) 0%, rgba(0,6,0,0.3) 50%, rgba(0,6,0,0.8) 100%)' }} />
      <div ref={ref} className="d2-hero-grid" style={{ position: 'relative', zIndex: 3, maxWidth: 1280, margin: '0 auto', width: '100%', padding: '120px 60px 80px', display: 'grid', gridTemplateColumns: '1.1fr 0.9fr', gap: 60, alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 11, color: G, letterSpacing: '0.2em', marginBottom: 24, fontFamily: "'JetBrains Mono', monospace" }}>
            $ projivo --init &gt;&gt; SYSTEM READY
          </div>
          <h1 style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 'clamp(36px, 5vw, 72px)', fontWeight: 700, lineHeight: 1.08, margin: '0 0 8px', color: '#fff', whiteSpace: 'pre-line' }}>
            {displayed}{!done && <Cursor />}
          </h1>
          <div style={{ fontSize: 11, color: '#223344', marginBottom: 40, fontFamily: "'JetBrains Mono', monospace", letterSpacing: '0.08em' }}>
            BUILT FOR PEOPLE WHO BUILD THINGS
          </div>
          <p style={{ fontSize: 15, color: '#6688aa', lineHeight: 1.7, maxWidth: 420, margin: '0 0 40px', fontFamily: "'JetBrains Mono', monospace", fontWeight: 300 }}>
            Tell Projivo what you're making. Get the tasks, timeline, budget, resources, and project workspace you need to actually start.
          </p>
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
            <a href={startUrl} style={{ background: G, color: '#000', padding: '10px 24px', fontSize: 13, fontWeight: 700, textDecoration: 'none', fontFamily: "'JetBrains Mono', monospace", letterSpacing: '0.06em' }}>
              $ start-building →
            </a>
            <a href={loginUrl} style={{ color: '#334455', fontSize: 12, textDecoration: 'none', fontFamily: "'JetBrains Mono', monospace" }}>log-in --silent</a>
          </div>
          <div style={{ marginTop: 16, fontSize: 11, color: '#223333', fontFamily: "'JetBrains Mono', monospace" }}>
            // free to start. no credit card required.
          </div>
        </div>
        <div aria-hidden="true" style={{ position: 'relative' }} />
      </div>
    </section>
  )
}

function Demo() {
  const lines = [
    { command: true, text: 'projivo create "grass seeding robot"' },
    { command: false, text: '→ Analyzing requirements...' },
    { command: false, text: '→ I want to build a robot that drives around my yard and plants grass seed in bare areas.' },
    { command: false, text: '' },
    { command: false, text: "? What's your budget, and do you already own any hardware?" },
    { command: true, text: 'Around $500–700. I already have a Raspberry Pi 5.' },
    { command: false, text: '✓ Project initialized.' },
  ]

  return (
    <section className="d2-section" style={{ padding: '80px 60px', background: '#000600', borderTop: '1px solid rgba(0,255,136,0.08)' }}>
      <div className="d2-container">
        <div style={{ fontFamily: "'JetBrains Mono', monospace", background: '#00080a', border: '1px solid rgba(0,255,136,0.15)', borderRadius: 4, padding: 32 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24, paddingBottom: 16, borderBottom: '1px solid rgba(0,255,136,0.1)' }}>
            {[G, B, '#334455'].map((color, index) => <div key={index} style={{ width: 10, height: 10, borderRadius: '50%', background: color }} />)}
            <span style={{ color: '#334455', fontSize: 11, marginLeft: 8 }}>projivo-session — bash</span>
          </div>
          <div className="d2-demo-columns" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 40 }}>
            <div>
              {lines.map((line, index) => (
                <div key={index} style={{ fontSize: 13, color: line.command ? '#fff' : line.text.startsWith('→') ? '#334455' : line.text.startsWith('?') ? B : G, marginBottom: 8, lineHeight: 1.5 }}>
                  {line.command ? <><span style={{ color: G }}>$ </span>{line.text}</> : line.text}
                </div>
              ))}
            </div>
            <div className="d2-demo-output" style={{ borderLeft: '1px solid rgba(0,255,136,0.1)', paddingLeft: 32 }}>
              <div style={{ fontSize: 11, color: '#334455', marginBottom: 12, letterSpacing: '0.12em' }}>OUTPUT: PROJECT_MANIFEST.json</div>
              <div style={{ fontSize: 12, color: '#6688aa', lineHeight: 1.8, whiteSpace: 'pre-line' }}>
                {'{\n  "name": "Grass Seeding Robot",\n  "description": "Raspberry Pi powered\n    autonomous lawn seeding robot.",\n  "tasks": 42,\n  "budget": "$618",\n  "timeline": "8 weeks",\n  "status": "initialized"\n}'}
              </div>
              <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid rgba(0,255,136,0.08)' }}>
                {['Define navigation requirements', 'Select motors and drivetrain', 'Build seed dispensing mechanism', 'Implement autonomous navigation'].map((task, index) => (
                  <div key={task} style={{ fontSize: 12, color: '#445566', marginBottom: 8, display: 'flex', gap: 8 }}>
                    <span style={{ color: '#223333' }}>[{String(index + 1).padStart(2, '0')}]</span><span>{task}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

function Problem() {
  const items = [
    { question: 'What will this cost?', answer: 'Parts, services, subscriptions, tools, and all the things you forgot.' },
    { question: 'What do I need?', answer: 'Technologies, components, resources, and decisions.' },
    { question: 'Where do I start?', answer: 'Turn one huge idea into the next actual thing you can do.' },
    { question: 'How long will this take?', answer: 'Tasks, dependencies, milestones, and a timeline that makes sense.' },
  ]

  return (
    <section className="d2-section" style={{ padding: '100px 60px', background: '#000', borderTop: '1px solid rgba(0,255,136,0.06)' }}>
      <div className="d2-container d2-problem-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 80 }}>
        <div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: G, letterSpacing: '0.15em', marginBottom: 20 }}>/* error_log */</div>
          <h2 style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 'clamp(32px, 4vw, 58px)', fontWeight: 700, color: '#fff', lineHeight: 1.1 }}>
            Ideas are fun.<br />Planning them <span style={{ color: G }}>sucks.</span>
          </h2>
        </div>
        <div style={{ fontFamily: "'JetBrains Mono', monospace" }}>
          <p style={{ fontSize: 14, color: '#6688aa', lineHeight: 1.8, marginBottom: 32, fontWeight: 300 }}>
            You know what you want to make. Then suddenly you're figuring out budgets, dependencies, parts, schedules, priorities, and what you're supposed to do first.
          </p>
          {items.map((item, index) => (
            <div key={item.question} style={{ borderLeft: '2px solid rgba(0,255,136,0.2)', paddingLeft: 20, marginBottom: 24 }}>
              <div style={{ fontSize: 13, color: B, marginBottom: 6 }}>[ERR_{String(index + 1).padStart(4, '0')}] {item.question}</div>
              <div style={{ fontSize: 12, color: '#445566', lineHeight: 1.6 }}>{item.answer}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function Projects() {
  const items = [
    { name: 'Autonomous Robot', description: 'Hardware, sensors, software, testing, parts, and a real budget.', tasks: 42, cost: '$614', time: '8 weeks' },
    { name: 'Indie Game', description: 'Gameplay systems, art, milestones, testing, and release.', tasks: 67, time: '4 months' },
    { name: 'Vacations', description: 'Tickets, Budget, Hotels, Events, and travel plans.', tasks: 31, time: '1 week' },
    { name: 'Home Server', description: 'Hardware selection, networking, setup, security, and services.', tasks: 18, cost: '$842' },
    { name: 'DIY Project', description: 'Materials, Budget, Instructions, and timeline.', tasks: 54, cost: '$376' },
    { name: 'SaaS Product', description: 'MVP scope, backend, frontend, deployment, and launch.', tasks: 38, time: '7 weeks' },
  ]

  return (
    <section id="features" className="d2-section" style={{ padding: '100px 60px', background: '#000600', borderTop: '1px solid rgba(0,255,136,0.06)' }}>
      <div className="d2-container">
        <div style={{ fontFamily: "'JetBrains Mono', monospace", marginBottom: 56 }}>
          <div style={{ fontSize: 11, color: '#334455', marginBottom: 8 }}>$ ls ~/projects</div>
          <h2 style={{ fontSize: 'clamp(28px, 3.5vw, 52px)', fontWeight: 700, color: '#fff', marginBottom: 12 }}>
            What do you want to <span style={{ color: G }}>build?</span>
          </h2>
          <p style={{ fontSize: 13, color: '#6688aa', fontWeight: 300 }}>
            Software. Hardware. Games. Robots. Weird weekend ideas. Projivo is built around the project, not the industry.
          </p>
        </div>
        <div className="d2-project-cards" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 2 }}>
          {items.map((item, index) => (
            <div key={item.name} style={{ padding: 20, fontFamily: "'JetBrains Mono', monospace", border: '1px solid rgba(0,255,136,0.08)', background: '#00080a', transition: 'border-color 0.2s' }}
              onMouseEnter={(event) => { event.currentTarget.style.borderColor = 'rgba(0,255,136,0.3)' }}
              onMouseLeave={(event) => { event.currentTarget.style.borderColor = 'rgba(0,255,136,0.08)' }}>
              <div style={{ fontSize: 10, color: '#334455', marginBottom: 8 }}>PROJECT_{String(index + 1).padStart(3, '0')}</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#fff', marginBottom: 8 }}>{item.name}</div>
              <p style={{ fontSize: 12, color: '#6688aa', marginBottom: 16, lineHeight: 1.6, fontWeight: 300 }}>{item.description}</p>
              <div style={{ display: 'flex', gap: 12 }}>
                <span style={{ fontSize: 11, color: G }}>{item.tasks}T</span>
                {item.cost && <span style={{ fontSize: 11, color: B }}>{item.cost}</span>}
                {item.time && <span style={{ fontSize: 11, color: '#445566' }}>{item.time}</span>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function Budget() {
  const costs: [string, string, string][] = [
    ['Drive System', '$142', G], ['Sensors', '$118', B], ['Power', '$100', G],
    ['Chassis & Hardware', '$116', B], ['Seed System', '$102', G], ['Miscellaneous', '$40', '#445566'],
  ]

  return (
    <section className="d2-section" style={{ padding: '100px 60px', background: '#000', borderTop: '1px solid rgba(0,255,136,0.06)' }}>
      <div className="d2-container d2-budget-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 80, alignItems: 'start' }}>
        <div style={{ fontFamily: "'JetBrains Mono', monospace" }}>
          <div style={{ fontSize: 11, color: G, letterSpacing: '0.15em', marginBottom: 20 }}>/* budget_module */</div>
          <h2 style={{ fontSize: 'clamp(28px, 3.5vw, 52px)', fontWeight: 700, color: '#fff', marginBottom: 24, lineHeight: 1.1 }}>
            Your project budget,<br /><span style={{ color: B }}>figured out for you.</span>
          </h2>
          <p style={{ fontSize: 13, color: '#6688aa', lineHeight: 1.8, marginBottom: 32, fontWeight: 300 }}>
            Projivo breaks your project down into the things you'll actually need, estimates the cost, and keeps your budget updated as your project changes.
          </p>
          {[
            { icon: '→', title: 'Cost breakdown', description: 'See exactly where your money is going.' },
            { icon: '⟳', title: 'Updates automatically', description: 'Change your project and the budget changes with it.' },
            { icon: '⊞', title: 'Know what to buy', description: 'Turn your budget into an actionable parts list.' },
          ].map((feature) => (
            <div key={feature.title} style={{ display: 'flex', gap: 12, marginBottom: 20, padding: '12px 0', borderBottom: '1px solid rgba(0,255,136,0.08)' }}>
              <span style={{ color: G, fontSize: 14, width: 20 }}>{feature.icon}</span>
              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#fff', marginBottom: 4 }}>{feature.title}</div>
                <div style={{ fontSize: 12, color: '#6688aa', fontWeight: 300 }}>{feature.description}</div>
              </div>
            </div>
          ))}
        </div>
        <div style={{ fontFamily: "'JetBrains Mono', monospace", background: '#00080a', border: '1px solid rgba(0,255,136,0.12)', padding: 24 }}>
          <div style={{ fontSize: 10, color: G, letterSpacing: '0.12em', marginBottom: 16 }}>PROJECT BUDGET :: Grass Seeding Robot</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 11, color: '#445566' }}>ESTIMATED_TOTAL</span><span style={{ fontSize: 16, color: G, fontWeight: 700 }}>$618</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20 }}>
            <span style={{ fontSize: 11, color: '#445566' }}>BUDGET_USED</span><span style={{ fontSize: 11, color: '#fff' }}>$412 / $700</span>
          </div>
          <div style={{ height: 2, background: '#001100', marginBottom: 20 }}><div style={{ height: '100%', width: '59%', background: G, boxShadow: `0 0 6px ${G}` }} /></div>
          {costs.map(([category, cost, color]) => (
            <div key={category} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid rgba(0,255,136,0.05)' }}>
              <span style={{ fontSize: 12, color: '#6688aa' }}>{category}</span><span style={{ fontSize: 12, color, fontWeight: 700 }}>{cost}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function System() {
  const features = [
    { name: 'Tasks', description: 'What to do next' },
    { name: 'Timeline', description: 'When it happens' },
    { name: 'Budget', description: 'What it costs' },
    { name: 'Resources', description: 'What you need' },
    { name: 'Team', description: 'Who owns what' },
    { name: 'Project Health', description: "What's going wrong" },
  ]

  return (
    <section className="d2-section" style={{ padding: '100px 60px', background: '#000600', borderTop: '1px solid rgba(0,255,136,0.06)' }}>
      <div className="d2-container d2-system-grid" style={{ fontFamily: "'JetBrains Mono', monospace", display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 80, alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 11, color: G, letterSpacing: '0.15em', marginBottom: 20 }}>/* system_modules */</div>
          <h2 style={{ fontSize: 'clamp(28px, 3.5vw, 52px)', fontWeight: 700, color: '#fff', lineHeight: 1.1 }}>
            Everything between<br /><span style={{ color: B }}>&quot;I have an idea&quot;</span><br />and<br /><span style={{ color: G }}>&quot;I built it.&quot;</span>
          </h2>
        </div>
        <div>
          <div style={{ fontSize: 11, color: '#334455', marginBottom: 16 }}>$ projivo modules --list</div>
          {features.map((feature, index) => (
            <div key={feature.name} style={{ display: 'flex', justifyContent: 'space-between', padding: '12px 0', borderBottom: '1px solid rgba(0,255,136,0.06)', alignItems: 'center', gap: 12 }}>
              <div><span style={{ color: '#223333', marginRight: 10, fontSize: 11 }}>[{String(index + 1).padStart(2, '0')}]</span><span style={{ fontSize: 13, color: '#fff', fontWeight: 600 }}>{feature.name}</span></div>
              <span style={{ fontSize: 12, color: '#6688aa' }}>{feature.description}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function ChatSection() {
  const conversations = [
    { user: 'I already own the Raspberry Pi.', label: 'Budget updated.', detail: 'Raspberry Pi 5 removed from expected purchases. $684 → $604' },
    { user: 'Johnny is handling the backend.', label: 'Tasks reassigned.', detail: 'Backend tasks assigned to John based on role and workload.' },
    { user: 'I need this finished by September.', label: 'Timeline adjusted.', detail: 'Tasks rescheduled and parallel work identified.' },
  ]

  return (
    <section className="d2-section" style={{ padding: '100px 60px', background: '#000', borderTop: '1px solid rgba(0,255,136,0.06)' }}>
      <div className="d2-container d2-chat-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 80, alignItems: 'center' }}>
        <div style={{ fontFamily: "'JetBrains Mono', monospace" }}>
          <div style={{ fontSize: 11, color: G, letterSpacing: '0.15em', marginBottom: 20 }}>/* interactive_mode */</div>
          <h2 style={{ fontSize: 'clamp(32px, 4vw, 62px)', fontWeight: 700, color: '#fff', marginBottom: 20 }}>
            Just talk<br />to it.<Cursor />
          </h2>
          <p style={{ fontSize: 13, color: '#6688aa', lineHeight: 1.8, fontWeight: 300 }}>Your project changes. Projivo should change with it.</p>
        </div>
        <div style={{ fontFamily: "'JetBrains Mono', monospace" }}>
          {conversations.map((conversation) => (
            <div key={conversation.user} style={{ background: '#00080a', border: '1px solid rgba(0,255,136,0.1)', padding: '16px 18px', marginBottom: 12 }}>
              <div style={{ fontSize: 12, color: '#fff', marginBottom: 10 }}><span style={{ color: G }}>$ </span>&quot;{conversation.user}&quot;</div>
              <div style={{ fontSize: 11, color: G, fontWeight: 700, marginBottom: 4 }}>✓ {conversation.label}</div>
              <div style={{ fontSize: 11, color: '#445566' }}>{conversation.detail}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function FinalCTA({ startUrl }: Pick<Design2Props, 'startUrl'>) {
  return (
    <section className="d2-section" style={{ position: 'relative', padding: '120px 60px', textAlign: 'center', overflow: 'hidden', background: '#000600' }}>
      <video src={VIDEO} autoPlay muted loop playsInline aria-hidden="true" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', opacity: 0.2, filter: 'hue-rotate(100deg)' }} />
      <ScanLines />
      <div aria-hidden="true" style={{ position: 'absolute', inset: 0, background: 'radial-gradient(ellipse at center, rgba(0,255,136,0.06) 0%, rgba(0,6,0,0.9) 70%)' }} />
      <div style={{ position: 'relative', zIndex: 3, fontFamily: "'JetBrains Mono', monospace" }}>
        <div style={{ fontSize: 11, color: G, letterSpacing: '0.2em', marginBottom: 20 }}>$ quit --stalling</div>
        <h2 style={{ fontSize: 'clamp(42px, 6vw, 90px)', fontWeight: 700, color: '#fff', marginBottom: 24, lineHeight: 1 }}>
          Build Your<br /><span style={{ color: G }}>Dream Project</span>
        </h2>
        <p style={{ fontSize: 14, color: '#6688aa', maxWidth: 440, margin: '0 auto 40px', lineHeight: 1.8, fontWeight: 300 }}>
          Stop planning the project in your head. Turn it into something you can actually start building.
        </p>
        <a href={startUrl} style={{ display: 'inline-block', background: G, color: '#000', padding: '12px 32px', fontSize: 14, fontWeight: 700, textDecoration: 'none', letterSpacing: '0.08em' }}>
          $ start-your-project →
        </a>
      </div>
    </section>
  )
}

export default function Design2(props: Design2Props) {
  return (
    <div className="design2-page" style={{ background: '#000', color: '#fff', fontFamily: "'JetBrains Mono', monospace" }}>
      <Nav {...props} />
      <div style={{ paddingTop: 52 }}>
        <Hero startUrl={props.startUrl} loginUrl={props.loginUrl} />
        <Demo />
        <Problem />
        <Projects />
        <Budget />
        <System />
        <ChatSection />
        <FinalCTA startUrl={props.startUrl} />
        <footer id="footer" style={{ padding: '32px 60px', borderTop: '1px solid rgba(0,255,136,0.06)', fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#223333' }}>
          <span style={{ color: G }}>// </span>Projivo · Built for people who build things.<br />
          <span style={{ color: G }}>// </span>AI-generated project guidance should be reviewed before making financial, legal, safety, or engineering decisions.
        </footer>
      </div>
    </div>
  )
}