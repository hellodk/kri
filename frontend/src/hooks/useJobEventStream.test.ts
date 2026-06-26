/**
 * Tests for the pure helpers of the job-event push hook (#756 / ARC-11, #921):
 *   - parseEventFrame: SSE wire frame → JobEvent | null
 *   - queryKeysForEvent: JobEvent → React Query keys to invalidate
 */
import { describe, it, expect } from 'vitest'
import { parseEventFrame, queryKeysForEvent, type JobEvent } from './useJobEventStream'

describe('parseEventFrame', () => {
  it('parses a well-formed data frame', () => {
    const frame = 'data: {"kind":"ansible_job","id":"j1","status":"running"}'
    expect(parseEventFrame(frame)).toEqual({ kind: 'ansible_job', id: 'j1', status: 'running' })
  })

  it('tolerates no space after the data: prefix', () => {
    const frame = 'data:{"kind":"bootstrap","id":"n1","status":"completed"}'
    expect(parseEventFrame(frame)?.status).toBe('completed')
  })

  it('returns null for comment/keepalive frames', () => {
    expect(parseEventFrame(': keepalive')).toBeNull()
    expect(parseEventFrame(': connected')).toBeNull()
  })

  it('returns null for the [DONE] sentinel and empty payloads', () => {
    expect(parseEventFrame('data: [DONE]')).toBeNull()
    expect(parseEventFrame('data:')).toBeNull()
  })

  it('returns null for malformed JSON', () => {
    expect(parseEventFrame('data: {not json')).toBeNull()
  })

  it('returns null when required fields are missing', () => {
    expect(parseEventFrame('data: {"kind":"ansible_job"}')).toBeNull()
  })
})

describe('queryKeysForEvent', () => {
  it('maps an ansible_job event to its job + node-scoped lists', () => {
    const ev: JobEvent = { kind: 'ansible_job', id: 'j1', status: 'completed', node_id: 'n1' }
    expect(queryKeysForEvent(ev)).toEqual([
      ['ansible-job', 'j1'],
      ['ansible-jobs-node', 'n1'],
      ['executions-node', 'n1'],
    ])
  })

  it('omits node-scoped keys when node_id is absent', () => {
    const ev: JobEvent = { kind: 'ansible_job', id: 'j1', status: 'running' }
    expect(queryKeysForEvent(ev)).toEqual([['ansible-job', 'j1']])
  })

  it('maps a bootstrap event to status/logs/node/fleet keys', () => {
    const ev: JobEvent = { kind: 'bootstrap', id: 'n1', status: 'completed' }
    expect(queryKeysForEvent(ev)).toEqual([
      ['bootstrap-status', 'n1'],
      ['bootstrap-logs', 'n1'],
      ['node', 'n1'],
      ['nodes'],
      ['fleet-overview'],
    ])
  })

  it('maps a salt_job event to job + executions list keys', () => {
    const ev: JobEvent = { kind: 'salt_job', id: 'j2', status: 'completed', node_id: 'n2' }
    expect(queryKeysForEvent(ev)).toEqual([
      ['job', 'j2'],
      ['executions'],
      ['executions-node', 'n2'],
    ])
  })

  it('maps a salt_job event without node_id to job + executions keys only', () => {
    const ev: JobEvent = { kind: 'salt_job', id: 'j3', status: 'completed' }
    expect(queryKeysForEvent(ev)).toEqual([
      ['job', 'j3'],
      ['executions'],
    ])
  })

  it('returns no keys for an unknown kind', () => {
    expect(queryKeysForEvent({ kind: 'other', id: 'x', status: 'running' })).toEqual([])
  })
})
