/**
 * Tests for #830 — Advanced bootstrap options section in BootstrapModal.
 *
 * TDD: written FIRST (red) before the implementation makes them green.
 *
 * Asserts that SingleMode renders an "Advanced" collapsible section with
 * node_exporter_version, node_exporter_listen_address, and node_exporter_url_override
 * fields, and that their values are passed to ansibleApi.bootstrap().
 *
 * Note: the bootstrap_full toggle was removed (#625) — brew inventory + the
 * telemetry deps now run on every bootstrap — so this no longer asserts it.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { BootstrapModal } from './BootstrapModal'

// ── Mocks ──────────────────────────────────────────────────────────────────────

vi.mock('../api/ansible', () => ({
  ansibleApi: {
    getSettings: vi.fn().mockResolvedValue({ ssh_bootstrap_username: 'admin' }),
    bootstrap: vi.fn().mockResolvedValue({ node_id: 'node-1', minion_id: 'mm1', job_id: 'job-1', bootstrap_status: 'pending', message: 'ok' }),
    bootstrapStatus: vi.fn().mockResolvedValue({ bootstrap_status: 'pending', bootstrap_error: null }),
    bootstrapLogs: vi.fn().mockResolvedValue({ ansible_stdout: null }),
    playbookContent: vi.fn().mockResolvedValue({ content: '---\n# playbook' }),
  },
}))

vi.mock('../api/search', () => ({
  searchApi: {
    search: vi.fn().mockResolvedValue({ items: [] }),
  },
}))

vi.mock('../api/fleet', () => ({
  fleetApi: {
    nodes: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    node: vi.fn().mockResolvedValue(null),
  },
}))

vi.mock('../api/groups', () => ({
  groupsApi: {
    list: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    members: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  },
}))

vi.mock('../api/saltMasters', () => ({
  saltMastersApi: {
    list: vi.fn().mockResolvedValue([{ id: 'sm-1', name: 'mm1', address: '10.0.0.1', status: 'reachable', enabled: true }]),
  },
}))

vi.mock('../stores/toastStore', () => ({
  useToastStore: () => vi.fn(),
}))

// ── Helpers ────────────────────────────────────────────────────────────────────

function renderModal() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <BootstrapModal onClose={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('BootstrapModal — Advanced options (issue #830)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders an "Advanced" toggle button in SingleMode', async () => {
    renderModal()
    // Should show a toggle for the advanced section
    await waitFor(() => {
      const toggle = screen.getByRole('button', { name: /advanced/i })
      expect(toggle).toBeInTheDocument()
    })
  })

  it('advanced section is collapsed by default (fields not visible)', async () => {
    renderModal()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /advanced/i })).toBeInTheDocument()
    })
    // These inputs should NOT be visible before expanding
    expect(screen.queryByPlaceholderText('1.8.2')).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText(':9100')).not.toBeInTheDocument()
  })

  it('expands advanced section when toggle is clicked', async () => {
    renderModal()
    const user = userEvent.setup()
    await waitFor(() => screen.getByRole('button', { name: /advanced/i }))

    await user.click(screen.getByRole('button', { name: /advanced/i }))

    // node_exporter version input
    await waitFor(() => {
      expect(screen.getByPlaceholderText('1.8.2')).toBeInTheDocument()
    })
    // listen address input
    expect(screen.getByPlaceholderText(':9100')).toBeInTheDocument()
  })

  it('default values are pre-filled in advanced fields', async () => {
    renderModal()
    const user = userEvent.setup()
    await waitFor(() => screen.getByRole('button', { name: /advanced/i }))
    await user.click(screen.getByRole('button', { name: /advanced/i }))

    await waitFor(() => {
      const versionInput = screen.getByPlaceholderText('1.8.2') as HTMLInputElement
      expect(versionInput.value).toBe('1.8.2')

      const listenInput = screen.getByPlaceholderText(':9100') as HTMLInputElement
      expect(listenInput.value).toBe(':9100')
    })
  })

  it('passes advanced values to ansibleApi.bootstrap when form is submitted', async () => {
    const { ansibleApi } = await import('../api/ansible')
    renderModal()
    const user = userEvent.setup()

    // Wait for settings + salt masters to load (advanced button and master list appear)
    await waitFor(() => screen.getByRole('button', { name: /advanced/i }))
    await waitFor(() => screen.getByText('mm1'))

    // Switch to "New node" tab
    await user.click(screen.getByRole('button', { name: /new node/i }))

    // Fill minion ID and IP
    await user.type(screen.getByPlaceholderText('mac-mini-01'), 'test-node')
    await user.type(screen.getByPlaceholderText('10.0.1.11'), '10.0.0.99')

    // Username is pre-filled from settings ('admin'); just ensure password is set
    await user.type(screen.getByPlaceholderText('••••••••'), 'password')

    // Expand advanced section
    await user.click(screen.getByRole('button', { name: /advanced/i }))
    await waitFor(() => screen.getByPlaceholderText('1.8.2'))

    // Change version to non-default
    const versionInput = screen.getByPlaceholderText('1.8.2')
    await user.clear(versionInput)
    await user.type(versionInput, '1.9.0')

    // Submit — button may be disabled until canSubmit; findByRole waits
    const submitBtn = await screen.findByRole('button', { name: /^bootstrap$/i })
    await user.click(submitBtn)

    await waitFor(() => {
      expect(ansibleApi.bootstrap).toHaveBeenCalled()
      const [, , , , , opts] = (ansibleApi.bootstrap as ReturnType<typeof vi.fn>).mock.calls[0]
      expect(opts).toMatchObject({
        nodeExporterVersion: '1.9.0',
      })
    })
  })
})

describe('BootstrapModal — master-first bootstrap (issue #1019)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the "Also make this node a salt-master" checkbox, unchecked by default', async () => {
    renderModal()
    await waitFor(() => screen.getByText('mm1'))

    const checkbox = screen.getByRole('checkbox', { name: /also make this node a salt-master/i })
    expect(checkbox).toBeInTheDocument()
    expect(checkbox).not.toBeChecked()
  })

  it('passes as_master via the asMaster option to ansibleApi.bootstrap when the toggle is checked', async () => {
    const { ansibleApi } = await import('../api/ansible')
    renderModal()
    const user = userEvent.setup()

    await waitFor(() => screen.getByText('mm1'))

    // Switch to "New node" tab
    await user.click(screen.getByRole('button', { name: /new node/i }))

    // Fill minion ID and IP
    await user.type(screen.getByPlaceholderText('mac-mini-01'), 'test-node')
    await user.type(screen.getByPlaceholderText('10.0.1.11'), '10.0.0.99')
    await user.type(screen.getByPlaceholderText('••••••••'), 'password')

    // Check the "Also make this node a salt-master" toggle
    const checkbox = screen.getByRole('checkbox', { name: /also make this node a salt-master/i })
    await user.click(checkbox)
    expect(checkbox).toBeChecked()

    const submitBtn = await screen.findByRole('button', { name: /^bootstrap$/i })
    await user.click(submitBtn)

    await waitFor(() => {
      expect(ansibleApi.bootstrap).toHaveBeenCalled()
      const [, , , , , opts] = (ansibleApi.bootstrap as ReturnType<typeof vi.fn>).mock.calls[0]
      expect(opts).toMatchObject({
        asMaster: true,
      })
    })
  })
})
