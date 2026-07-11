/**
 * Regression test: the Bootstrap form must be reachable on "unregistered" nodes.
 *
 * Bug: the header "⊡ Bootstrap" button only flips `showRebootstrap`, but the
 * inline form used to live inside the "Bootstrap Status" card, which is hidden
 * for nodes with bootstrap_status === 'unregistered'. So clicking Bootstrap on a
 * never-bootstrapped node did nothing. The form is now rendered at the grid top
 * level, independent of the status card.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { OverviewTab } from './OverviewTab'
import type { NodeDetail as NodeDetailData } from '../../types'

// ── Mocks ──────────────────────────────────────────────────────────────────────

vi.mock('../../api/fleet', () => ({
  fleetApi: { addTag: vi.fn(), removeTag: vi.fn() },
}))
vi.mock('../../api/ansible', () => ({
  ansibleApi: { cancelBootstrap: vi.fn() },
}))
vi.mock('../../api/playbooks', () => ({
  playbooksApi: { run: vi.fn() },
}))
vi.mock('../../api/saltOps', () => ({
  saltOpsApi: { cmd: vi.fn() },
}))
vi.mock('../../api/client', () => ({
  api: { get: vi.fn().mockResolvedValue({}), post: vi.fn().mockResolvedValue({}) },
}))
vi.mock('../../stores/toastStore', () => ({
  useToastStore: () => vi.fn(),
}))
// Child panels fire their own queries — stub them out to isolate this test.
vi.mock('./ConnectivityPanel', () => ({ ConnectivityPanel: () => null }))
vi.mock('./ResolvedCredentialPanel', () => ({ ResolvedCredentialPanel: () => null }))

// ── Helpers ──────────────────────────────────────────────────────────────────────

function makeNode(overrides: Partial<NodeDetailData> = {}): NodeDetailData {
  return {
    id: 'node-1',
    minion_id: '192.168.1.64',
    hostname: '192.168.1.64',
    ip_address: '192.168.1.64',
    bootstrap_ip: null,
    bootstrap_status: 'unregistered',
    status: 'unknown',
    tags: [],
    ...overrides,
  } as unknown as NodeDetailData
}

function renderOverview(props: { showRebootstrap: boolean; node?: NodeDetailData }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <OverviewTab
          node={props.node ?? makeNode()}
          nodeId="node-1"
          nodeMaster={undefined}
          canManage={true}
          showRebootstrap={props.showRebootstrap}
          setShowRebootstrap={vi.fn()}
          rebootstrapIp="192.168.1.64"
          setRebootstrapIp={vi.fn()}
          refetchNode={vi.fn()}
        />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('OverviewTab — Bootstrap form on unregistered nodes', () => {
  it('shows the bootstrap form when showRebootstrap is true even though the node is unregistered', () => {
    renderOverview({ showRebootstrap: true })

    // The form (IP input + Confirm) must be present despite no Bootstrap Status card.
    expect(screen.getByPlaceholderText('Target IP address')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeInTheDocument()
    // First-time copy for never-bootstrapped nodes.
    expect(
      screen.getByText('This will run the bootstrap playbook on this node.')
    ).toBeInTheDocument()
  })

  it('keeps the Bootstrap Status card hidden for unregistered nodes', () => {
    renderOverview({ showRebootstrap: false })

    // Status card still suppressed for unregistered nodes…
    expect(screen.queryByText('Bootstrap Status')).not.toBeInTheDocument()
    // …and the form is not shown until the button is pressed.
    expect(screen.queryByPlaceholderText('Target IP address')).not.toBeInTheDocument()
  })
})
