import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ansibleApi, type PlaybookTreeNode } from '../api/ansible'
import { useToastStore } from '../stores/toastStore'
import type { PlaybookEntry } from '../api/playbooks'

const TYPE_ICONS: Record<string, string> = {
  playbook: '▤',
  role: '📁',
  tasks: '▷',
  handlers: '⚡',
  defaults: '⚙',
  vars: '📋',
  template: '🎨',
  file: '📄',
  meta: 'ℹ',
  include: '↩',
}

const TYPE_COLORS: Record<string, string> = {
  playbook: 'text-brand-600',
  role: 'text-purple-600',
  tasks: 'text-emerald-600',
  handlers: 'text-amber-600',
  defaults: 'text-gray-500',
  vars: 'text-blue-600',
  template: 'text-rose-600',
  file: 'text-gray-600',
  meta: 'text-gray-400',
  include: 'text-indigo-600',
}

function TreeItem({
  node,
  depth,
  selectedPath,
  onSelect,
}: {
  node: PlaybookTreeNode
  depth: number
  selectedPath: string | null
  onSelect: (node: PlaybookTreeNode) => void
}) {
  const [open, setOpen] = useState(depth < 2)
  const hasChildren = node.children && node.children.length > 0
  const icon = TYPE_ICONS[node.type] ?? '📄'
  const color = TYPE_COLORS[node.type] ?? 'text-gray-600'
  const isSelected = selectedPath === node.path
  const indent = depth * 12

  if (hasChildren) {
    return (
      <div>
        <button
          onClick={() => setOpen(!open)}
          className={`flex items-center w-full text-left py-1 px-2 rounded-lg hover:bg-gray-100 group ${isSelected ? 'bg-brand-50' : ''}`}
          style={{ paddingLeft: `${indent + 8}px` }}
        >
          <span className="text-gray-400 mr-1.5 text-xs">{open ? '▾' : '▸'}</span>
          <span className={`mr-1.5 text-xs ${color}`}>{icon}</span>
          <span className="text-xs font-medium text-gray-700 truncate">{node.label}</span>
          {!node.exists && <span className="ml-1 text-xs text-gray-300">(not found)</span>}
        </button>
        {open && node.children!.map((child, i) => (
          <TreeItem key={`${child.path}-${i}`} node={child} depth={depth + 1} selectedPath={selectedPath} onSelect={onSelect} />
        ))}
      </div>
    )
  }

  return (
    <button
      onClick={() => node.exists !== false && onSelect(node)}
      className={`flex items-center w-full text-left py-1 px-2 rounded-lg text-xs transition-colors ${
        isSelected
          ? 'bg-brand-100 text-brand-800'
          : node.exists === false
            ? 'text-gray-300 cursor-not-allowed'
            : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
      }`}
      style={{ paddingLeft: `${indent + 20}px` }}
      title={node.task_name ? `Task: ${node.task_name}` : undefined}
    >
      <span className={`mr-1.5 ${color}`}>{icon}</span>
      <span className="truncate font-mono">{node.label}</span>
      {node.task_name && (
        <span className="ml-auto text-gray-300 text-[10px] truncate max-w-[80px] pl-2">{node.task_name}</span>
      )}
    </button>
  )
}

export function PlaybookDrawer({
  playbook,
  onClose,
}: {
  playbook: PlaybookEntry
  onClose: () => void
}) {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [selectedNode, setSelectedNode] = useState<PlaybookTreeNode | null>(null)
  const [editedContent, setEditedContent] = useState<string | null>(null)
  const [isDirty, setIsDirty] = useState(false)

  const { data: tree, isLoading: treeLoading, isError: treeError } = useQuery({
    queryKey: ['playbook-tree', playbook.filename],
    queryFn: () => ansibleApi.playbookTree(playbook.filename),
    staleTime: 30_000,
  })

  const { data: fileData, isLoading: fileLoading, isError: fileError, error: fileErrorObj } = useQuery({
    queryKey: ['playbook-file-content', selectedNode?.path],
    queryFn: () => ansibleApi.getFileContent(selectedNode!.path),
    enabled: !!selectedNode && selectedNode.exists !== false,
    staleTime: 0,
    retry: false,
  })

  const saveMutation = useMutation({
    mutationFn: () => ansibleApi.updateFileContent(selectedNode!.path, editedContent ?? ''),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playbook-file-content', selectedNode?.path] })
      qc.invalidateQueries({ queryKey: ['playbooks'] })
      setIsDirty(false)
      toast('File saved')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  function handleSelect(node: PlaybookTreeNode) {
    if (isDirty && !confirm('Discard unsaved changes?')) return
    setSelectedNode(node)
    setEditedContent(null)
    setIsDirty(false)
  }

  function handleEdit(value: string) {
    setEditedContent(value)
    setIsDirty(value !== (fileData?.content ?? ''))
  }

  const displayContent = editedContent ?? fileData?.content ?? ''

  // Auto-select the first node (the playbook itself)
  if (!selectedNode && tree?.nodes.length) {
    const first = tree.nodes.find(n => n.type === 'playbook' && n.exists !== false)
      ?? tree.nodes.find(n => n.exists !== false)
    if (first) setTimeout(() => setSelectedNode(first), 0)
  }

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div className="flex-1 bg-black/40" onClick={onClose} />

      {/* Drawer */}
      <div className="w-full max-w-5xl bg-white shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 bg-gray-50 shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <span className={`text-xs px-2 py-0.5 rounded font-medium border ${
              playbook.entry_type === 'role'
                ? 'bg-purple-50 text-purple-700 border-purple-200'
                : 'bg-brand-50 text-brand-700 border-brand-200'
            }`}>
              {playbook.entry_type}
            </span>
            <h2 className="text-base font-bold text-gray-900 truncate">{playbook.name}</h2>
            <span className="text-xs text-gray-400 font-mono hidden sm:block">{playbook.filename}</span>
          </div>
          <button onClick={onClose} className="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-200 rounded-lg text-lg flex-shrink-0">×</button>
        </div>

        {/* Two-panel layout */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left: dependency tree */}
          <div className="w-64 shrink-0 border-r border-gray-200 flex flex-col">
            <div className="px-3 py-2 border-b border-gray-100 bg-gray-50">
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Files — Execution Order</p>
            </div>
            <div className="flex-1 overflow-y-auto py-1.5 px-1">
              {treeLoading ? (
                <p className="text-xs text-gray-400 px-3 py-2">Loading…</p>
              ) : treeError ? (
                <p className="text-xs text-red-400 px-3 py-2">Could not load tree</p>
              ) : tree?.nodes.length === 0 ? (
                <p className="text-xs text-gray-400 px-3 py-2">No files found</p>
              ) : (
                tree?.nodes.map((node, i) => (
                  <TreeItem
                    key={`${node.path}-${i}`}
                    node={node}
                    depth={0}
                    selectedPath={selectedNode?.path ?? null}
                    onSelect={handleSelect}
                  />
                ))
              )}
            </div>

            {/* Legend */}
            <div className="px-3 py-2 border-t border-gray-100 bg-gray-50 space-y-0.5">
              {[['🎨', 'template', 'Jinja2 template'], ['▷', 'tasks', 'Task list'], ['⚡', 'handlers', 'Handlers'], ['📋', 'vars', 'Variables']].map(([icon, , label]) => (
                <div key={label} className="flex items-center gap-1.5 text-[10px] text-gray-400">
                  <span>{icon}</span><span>{label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Right: editor */}
          <div className="flex-1 flex flex-col min-w-0">
            {selectedNode ? (
              <>
                {/* Editor header */}
                <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100 bg-gray-50 shrink-0">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`${TYPE_COLORS[selectedNode.type] ?? 'text-gray-500'} text-sm`}>
                      {TYPE_ICONS[selectedNode.type] ?? '📄'}
                    </span>
                    <code className="text-xs text-gray-700 truncate font-mono">{selectedNode.path}</code>
                    {isDirty && <span className="text-xs text-amber-600 font-semibold shrink-0">● unsaved</span>}
                  </div>
                  <div className="flex gap-2 shrink-0">
                    {isDirty && (
                      <button
                        onClick={() => { setEditedContent(null); setIsDirty(false) }}
                        className="px-3 py-1 text-xs border border-gray-200 rounded-lg text-gray-600 hover:bg-gray-100"
                      >Revert</button>
                    )}
                    <button
                      onClick={() => saveMutation.mutate()}
                      disabled={!isDirty || saveMutation.isPending}
                      className="px-3 py-1 text-xs bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-40"
                    >
                      {saveMutation.isPending ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                </div>
                {/* Editor */}
                <div className="flex-1 overflow-hidden">
                  {fileLoading ? (
                    <div className="flex items-center justify-center h-full text-sm text-gray-400">Loading…</div>
                  ) : fileError ? (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center space-y-2">
                        <p className="text-amber-500 text-sm font-medium">
                          <span className="mr-1">⚠</span>
                          File not found in playbooks directory
                        </p>
                        <code className="text-xs text-gray-400 font-mono block">{selectedNode?.path}</code>
                        <p className="text-xs text-gray-400">
                          {(fileErrorObj as any)?.message ?? 'Could not load file content'}
                        </p>
                      </div>
                    </div>
                  ) : !fileLoading && !displayContent && selectedNode?.exists !== false ? (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center space-y-2">
                        <p className="text-amber-500 text-sm gap-2">
                          <span>⚠</span>
                          <span> File not found: </span>
                          <code className="font-mono">{selectedNode?.path}</code>
                        </p>
                      </div>
                    </div>
                  ) : (
                    <textarea
                      className="w-full h-full resize-none font-mono text-xs p-4 focus:outline-none bg-gray-950 text-green-300 leading-relaxed"
                      value={displayContent}
                      onChange={e => handleEdit(e.target.value)}
                      spellCheck={false}
                      autoComplete="off"
                    />
                  )}
                </div>
              </>
            ) : (
              <div className="flex-1 flex items-center justify-center text-gray-400">
                <div className="text-center space-y-2">
                  <p className="text-2xl">👈</p>
                  <p className="text-sm">Select a file from the tree to view or edit</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
