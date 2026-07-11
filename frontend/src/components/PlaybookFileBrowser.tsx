import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FileText, FileCode, Wrench, Palette, Package, Folder, type LucideIcon } from 'lucide-react'
import { ansibleApi, type FileNode } from '../api/ansible'
import { useToastStore } from '../stores/toastStore'

function FileIcon({ ext }: { ext?: string }) {
  const icons: Record<string, LucideIcon> = {
    yml: FileText, yaml: FileText, py: FileCode, sh: Wrench, md: FileText, j2: Palette, ini: Wrench, cfg: Wrench, conf: Wrench, sls: Package,
  }
  const Icon = icons[ext ?? ''] ?? FileText
  return <Icon size={12} className="mr-1 shrink-0 inline" />
}

function TreeNode({
  node,
  depth,
  selected,
  onSelect,
}: {
  node: FileNode
  depth: number
  selected: string | null
  onSelect: (path: string) => void
}) {
  const [open, setOpen] = useState(depth === 0)
  const indent = depth * 12

  if (node.type === 'dir') {
    return (
      <div>
        <button
          onClick={() => setOpen(!open)}
          className="flex items-center w-full text-left py-0.5 px-2 hover:bg-gray-100 rounded text-xs text-gray-700"
          style={{ paddingLeft: `${indent + 8}px` }}
        >
          <span className="mr-1 text-gray-400">{open ? '▾' : '▸'}</span>
          <span className="font-medium">{node.name}</span>
        </button>
        {open && node.children?.map((child) => (
          <TreeNode key={child.path} node={child} depth={depth + 1} selected={selected} onSelect={onSelect} />
        ))}
      </div>
    )
  }

  return (
    <button
      onClick={() => onSelect(node.path)}
      className={`flex items-center w-full text-left py-0.5 px-2 rounded text-xs truncate ${
        selected === node.path
          ? 'bg-brand-50 text-brand-700 font-medium'
          : 'text-gray-600 hover:bg-gray-100'
      }`}
      style={{ paddingLeft: `${indent + 20}px` }}
    >
      <FileIcon ext={node.ext} />
      <span className="truncate">{node.name}</span>
    </button>
  )
}

export function PlaybookFileBrowser() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [editedContent, setEditedContent] = useState<string | null>(null)
  const [isDirty, setIsDirty] = useState(false)

  const { data: tree, isLoading: treeLoading } = useQuery({
    queryKey: ['playbook-files'],
    queryFn: ansibleApi.listFiles,
    staleTime: 30_000,
  })

  const { data: fileData, isLoading: fileLoading } = useQuery({
    queryKey: ['playbook-file-content', selectedPath],
    queryFn: () => ansibleApi.getFileContent(selectedPath!),
    enabled: !!selectedPath,
    staleTime: 0,
  })

  const saveMutation = useMutation({
    mutationFn: () => ansibleApi.updateFileContent(selectedPath!, editedContent ?? ''),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playbook-file-content', selectedPath] })
      qc.invalidateQueries({ queryKey: ['playbooks'] })
      setIsDirty(false)
      toast('File saved')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  function handleSelect(path: string) {
    if (isDirty && !confirm('Discard unsaved changes?')) return
    setSelectedPath(path)
    setEditedContent(null)
    setIsDirty(false)
  }

  function handleEdit(value: string) {
    setEditedContent(value)
    setIsDirty(value !== (fileData?.content ?? ''))
  }

  const displayContent = editedContent ?? fileData?.content ?? ''

  return (
    <div className="flex h-[70vh] border border-gray-200 rounded-xl overflow-hidden bg-white shadow-xs">
      {/* File tree */}
      <div className="w-64 shrink-0 border-r border-gray-200 flex flex-col">
        <div className="px-3 py-2 border-b border-gray-100 bg-gray-50">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Playbooks Directory</p>
          {tree && <p className="text-xs text-gray-400 font-mono truncate mt-0.5">{tree.root}</p>}
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {treeLoading ? (
            <p className="text-xs text-gray-400 px-3 py-2">Loading…</p>
          ) : tree?.tree.length === 0 ? (
            <p className="text-xs text-gray-400 px-3 py-2">No files found</p>
          ) : (
            tree?.tree.map((node) => (
              <TreeNode key={node.path} node={node} depth={0} selected={selectedPath} onSelect={handleSelect} />
            ))
          )}
        </div>
      </div>

      {/* Editor */}
      <div className="flex-1 flex flex-col min-w-0">
        {selectedPath ? (
          <>
            <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100 bg-gray-50 shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <code className="text-xs text-gray-600 truncate font-mono">{selectedPath}</code>
                {isDirty && <span className="text-xs text-amber-600 font-medium shrink-0">● unsaved</span>}
              </div>
              <div className="flex gap-2 shrink-0">
                {isDirty && (
                  <button
                    onClick={() => { setEditedContent(null); setIsDirty(false) }}
                    className="px-3 py-1 text-xs border border-gray-200 rounded-lg text-gray-600 hover:bg-gray-100"
                  >
                    Revert
                  </button>
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
            <div className="flex-1 overflow-hidden">
              {fileLoading ? (
                <div className="flex items-center justify-center h-full text-sm text-gray-400">Loading…</div>
              ) : (
                <textarea
                  className="w-full h-full resize-none font-mono text-xs p-4 focus:outline-hidden bg-gray-950 text-green-300 leading-relaxed"
                  value={displayContent}
                  onChange={(e) => handleEdit(e.target.value)}
                  spellCheck={false}
                  autoComplete="off"
                  autoCorrect="off"
                />
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-gray-400">
            <div className="text-center space-y-2">
              <Folder size={28} className="mx-auto text-gray-300" />
              <p>Select a file to view or edit</p>
              <p className="text-xs text-gray-300">Changes are saved directly to disk and affect all future runs</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
