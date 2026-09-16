import { useState, useEffect } from 'react'
import {
  Radar, LayoutGrid, MousePointerClick, PieChart, LineChart, BadgeCheck, CheckCircle2,
  X, ChevronLeft, ChevronRight,
} from 'lucide-react'

const STEPS = [
  { view: 'portfolio', icon: Radar, tint: 'bg-idbi-green/10 text-idbi-green', title: 'Welcome to DRISHTi',
    body: 'An early-warning system that flags MSME loans heading for default ~12 months ahead — so a bank officer can act while there’s still time. Here’s a 30-second tour.' },
  { view: 'portfolio', icon: LayoutGrid, tint: 'bg-idbi-green/10 text-idbi-green', title: '1 · The Watch-list',
    body: 'Every business in the book, ranked by risk and colour-coded — 🔴 act now, 🟠 watch, 🟢 healthy. The "Lead" column shows how many months of runway is left before trouble.' },
  { view: 'portfolio', icon: MousePointerClick, tint: 'bg-idbi-orange/10 text-idbi-orange', title: '2 · Click any account',
    body: 'Select a row to open its full story — a risk-over-time chart, the cash-flow slide behind it, plain-English reasons, and an auto-drafted alert memo. Try clicking a red one after the tour.' },
  { view: 'risk', icon: PieChart, tint: 'bg-idbi-green/10 text-idbi-green', title: '3 · Portfolio risk',
    body: 'See which sectors and segments are most stressed, and drag the what-if sliders to estimate the ₹ provisioning the bank saves by acting on the flags early.' },
  { view: 'analytics', icon: LineChart, tint: 'bg-idbi-green/10 text-idbi-green', title: '4 · Model & Metrics',
    body: 'The honest scorecard: realised NPA rate by risk band over 8 months, how early we catch trouble, calibration, and a leakage check proving the warnings come from cash-flow — not just "already late on payments".' },
  { view: 'real', icon: BadgeCheck, tint: 'bg-idbi-green/10 text-idbi-green', title: '5 · Real-data model',
    body: 'The proof: the same method run on ~3,200 REAL Indian MSMEs with real defaults — an honest 0.81. On synthetic data the score looks high; this is the number to trust.' },
  { view: 'portfolio', icon: CheckCircle2, tint: 'bg-idbi-green/10 text-idbi-green', title: 'You’re all set',
    body: 'The cockpit runs on synthetic demo data (plus the real-data validation tab). Explore freely — you can reopen this tour anytime from the “Tour” button at the top.' },
]

export default function Guide({ setView, setSelected, onClose }) {
  const [step, setStep] = useState(0)
  const s = STEPS[step]
  const last = step === STEPS.length - 1

  useEffect(() => {
    setSelected(null)
    setView(STEPS[step].view)
  }, [step, setView, setSelected])

  const Icon = s.icon
  return (
    <div className="fixed inset-x-0 bottom-5 z-50 flex justify-center px-4 pointer-events-none">
      <div className="pointer-events-auto w-full max-w-lg bg-white rounded-2xl border border-slate-200 shadow-2xl p-5 relative animate-[fadeup_.25s_ease]">
        <button onClick={onClose} className="absolute top-3 right-3 text-slate-400 hover:text-slate-700" aria-label="Close tour">
          <X size={18} />
        </button>
        <div className="flex items-start gap-3">
          <div className={`w-10 h-10 rounded-xl grid place-items-center shrink-0 ${s.tint}`}><Icon size={20} /></div>
          <div className="flex-1 min-w-0">
            <h3 className="font-extrabold text-slate-900">{s.title}</h3>
            <p className="text-sm text-slate-600 mt-1 leading-relaxed">{s.body}</p>
          </div>
        </div>

        <div className="flex items-center justify-between mt-4">
          <div className="flex gap-1.5">
            {STEPS.map((_, i) => (
              <button key={i} onClick={() => setStep(i)} aria-label={`Step ${i + 1}`}
                className={`h-1.5 rounded-full transition-all ${i === step ? 'w-5 bg-idbi-green' : 'w-1.5 bg-slate-200 hover:bg-slate-300'}`} />
            ))}
          </div>
          <div className="flex items-center gap-2">
            {step > 0 && (
              <button onClick={() => setStep(step - 1)}
                className="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800 px-2 py-1.5">
                <ChevronLeft size={15} /> Back
              </button>
            )}
            {!last ? (
              <button onClick={() => setStep(step + 1)}
                className="flex items-center gap-1 text-sm font-semibold text-white bg-idbi-green hover:bg-idbi-greenlt rounded-lg px-3.5 py-1.5">
                Next <ChevronRight size={15} />
              </button>
            ) : (
              <button onClick={onClose}
                className="flex items-center gap-1 text-sm font-semibold text-white bg-idbi-green hover:bg-idbi-greenlt rounded-lg px-4 py-1.5">
                Explore <ChevronRight size={15} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
