interface Props {
  page: number
  total: number
  perPage: number
  onPage: (p: number) => void
  onPerPage?: (n: number) => void
}

export function Pagination({ page, total, perPage, onPage, onPerPage }: Props) {
  const totalPages = Math.ceil(total / perPage)
  const from = (page - 1) * perPage + 1
  const to = Math.min(page * perPage, total)

  return (
    <div className="px-4 py-3 border-t border-gray-200 flex items-center justify-between gap-4 text-sm">
      <span className="text-gray-500 text-xs">
        Showing {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-2">
        {onPerPage && (
          <select
            value={perPage}
            onChange={(e) => { onPerPage(Number(e.target.value)); onPage(1) }}
            className="text-xs border border-gray-300 rounded px-2 py-1 text-gray-600 focus:outline-none focus:border-brand-600"
          >
            {[25, 50, 100].map((n) => (
              <option key={n} value={n}>{n} / page</option>
            ))}
          </select>
        )}
        <button disabled={page <= 1} onClick={() => onPage(page - 1)}
          className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed">
          ← Prev
        </button>
        <span className="text-xs text-gray-500">{page} / {totalPages || 1}</span>
        <button disabled={page >= totalPages} onClick={() => onPage(page + 1)}
          className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed">
          Next →
        </button>
      </div>
    </div>
  )
}
