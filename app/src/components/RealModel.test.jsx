import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import RealModel from './RealModel'
import realModel from '../../public/real_model.json'

/**
 * The three denominators on this screen are not interchangeable, and the AUC is the top of
 * a range rather than a point estimate. The repo's own README spells both out; the screen
 * used to print "1,284 real defaults" (the row count under the wrong noun) and 0.81 as a
 * flat headline. These guard the corrected wording.
 */
describe('RealModel — the honesty wording', () => {
  const draw = () => render(<RealModel data={realModel} syntheticAuc={0.95} />)

  it('calls the positive count rows, never "real defaults"', () => {
    draw()
    expect(document.body.textContent).not.toMatch(/real defaults/)
    expect(screen.getAllByText(/positive/i).length).toBeGreaterThan(0)
  })

  it('keeps the three denominators apart on screen', () => {
    draw()
    expect(screen.getByText(/Read the three denominators apart/)).toBeInTheDocument()
    expect(document.body.textContent).toMatch(/company-year rows/)
  })

  it('presents the AUC as the ceiling of a range, not a point estimate', () => {
    draw()
    expect(screen.getByText(/is the ceiling of a range, not a point estimate/)).toBeInTheDocument()
    expect(document.body.textContent).toMatch(/most permissive of four/)
    expect(screen.getByText(/Real-data ROC-AUC \(ceiling\)/)).toBeInTheDocument()
  })

  it('keeps the synthetic caveat beside it', () => {
    draw()
    expect(document.body.textContent).toMatch(/is illustrative, not a real-world claim/)
  })

  // `drishti/metrics` is A/M/CO only, so a relationship manager reaches this screen with
  // no cockpit AUC. It used to print a hard-coded 0.95 in that case — a number no run
  // produced.
  it('prints no cockpit score at all when the role cannot read the metrics', () => {
    render(<RealModel data={realModel} syntheticAuc={undefined} />)
    expect(document.body.textContent).toMatch(/its score is illustrative/)
    expect(document.body.textContent).not.toMatch(/~0\.95/)
  })
})
