import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { filterEpisodes, formatMetric, parseStudioReport } from './evaluationStudio'

function fixture(): unknown {
  return JSON.parse(
    readFileSync(new URL('../../public/evals/studio-v1.json', import.meta.url), 'utf8'),
  )
}

describe('Evaluation Studio report', () => {
  it('parses paired Fixture and keeps Live aggregate separate', () => {
    const report = parseStudioReport(fixture())
    expect(report.comparison.evidence_class).toBe('FIXTURE_EVALUATION')
    expect(report.historical_live?.evidence_class).toBe('LIVE_LLM_EVALUATION')
    expect(report.episodes).toHaveLength(report.comparison.paired_episodes * 2)
  })

  it('rejects missing pair members and unknown report versions', () => {
    const report = parseStudioReport(fixture())
    expect(() => parseStudioReport({ ...report, version: 2 })).toThrow()
    expect(() => parseStudioReport({ ...report, episodes: report.episodes.slice(1) })).toThrow()
    expect(() =>
      parseStudioReport({
        ...report,
        historical_live: {
          ...report.historical_live,
          evidence_class: 'FIXTURE_EVALUATION',
        },
      }),
    ).toThrow()
  })

  it('rejects aggregates that disagree with the recorded pairs', () => {
    const report = parseStudioReport(fixture())
    const staleCategory = structuredClone(report)
    staleCategory.comparison.single.per_category.B2.denominator = 999
    expect(() => parseStudioReport(staleCategory)).toThrow()
    const staleClusters = structuredClone(report)
    staleClusters.comparison.cluster_count++
    expect(() => parseStudioReport(staleClusters)).toThrow()
    const staleDelta = structuredClone(report)
    staleDelta.comparison.multi_minus_single.success_rate = 0.75
    expect(() => parseStudioReport(staleDelta)).toThrow()
    const malformed = [
      { ...report.episodes[0], error_code: { raw: 'not public' } },
      ...report.episodes.slice(1),
    ]
    expect(() => parseStudioReport({ ...report, episodes: malformed })).toThrow()
  })

  it('filters diagnostic status independently of Oracle verdict', () => {
    const report = parseStudioReport(fixture())
    const partial = filterEpisodes(report.episodes, {
      task: 'B2_03',
      category: 'B2',
      architecture: 'multi',
      status: 'PARTIAL',
      verdict: 'attention',
    })
    expect(partial).toHaveLength(1)
    expect(partial[0].success).toBe(true)
    expect(partial[0].business_effects.aftersales_cases).toBe(1)
    expect(filterEpisodes(report.episodes, { verdict: 'failed' })).toEqual([])
  })

  it('keeps missing and inapplicable distinct from observed zero', () => {
    expect(formatMetric('UNKNOWN')).toBe('UNKNOWN')
    expect(formatMetric('NOT_APPLICABLE')).toBe('NOT_APPLICABLE')
    expect(formatMetric(undefined)).toBe('UNKNOWN')
    expect(formatMetric(0)).toBe('0')
  })
})
