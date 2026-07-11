import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Sparkles, RefreshCw, Lightbulb } from 'lucide-react'
import { getLatestRecommendation, generateRecommendations } from '../api/recommendations'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'

function formatIst(iso: string): string {
  return (
    new Date(iso).toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }) + ' IST'
  )
}

export function RecommendationsPage() {
  const qc = useQueryClient()

  const { data: rec, isLoading, isError, refetch } = useQuery({
    queryKey: ['recommendations'],
    queryFn: getLatestRecommendation,
  })

  const generateMut = useMutation({
    mutationFn: generateRecommendations,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['recommendations'] })
    },
  })

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">AI Recommendations</h1>
          <p className="text-sm text-gray-600 mt-1">
            LLM-generated guidance based on the current state of your fleet.
          </p>
        </div>
        <button
          onClick={() => generateMut.mutate()}
          disabled={generateMut.isPending}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 disabled:opacity-50 transition-colors shrink-0"
        >
          {generateMut.isPending ? (
            <>
              <RefreshCw size={16} className="animate-spin" />
              Generating…
            </>
          ) : (
            <>
              <Sparkles size={16} />
              Regenerate now
            </>
          )}
        </button>
      </div>

      {generateMut.isError && (
        <div className="px-4 py-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
          {generateMut.error instanceof Error ? generateMut.error.message : 'Failed to generate recommendations'}
        </div>
      )}

      {isLoading ? (
        <div className="bg-white rounded-lg shadow-xs border border-gray-200">
          <Skeleton rows={6} />
        </div>
      ) : isError ? (
        <ErrorState message="Failed to load recommendations" retry={refetch} />
      ) : !rec ? (
        <div className="flex flex-col items-center justify-center py-20 text-center bg-white rounded-lg shadow-xs border border-gray-200">
          <Lightbulb size={40} className="text-gray-300 mb-3" />
          <p className="text-gray-700 font-medium">No recommendations yet</p>
          <p className="text-sm text-gray-500 mt-1 mb-4 max-w-sm">
            Generate the first set of AI recommendations for your fleet.
          </p>
          <button
            onClick={() => generateMut.mutate()}
            disabled={generateMut.isPending}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 disabled:opacity-50 transition-colors"
          >
            {generateMut.isPending ? (
              <>
                <RefreshCw size={16} className="animate-spin" />
                Generating…
              </>
            ) : (
              <>
                <Sparkles size={16} />
                Regenerate now
              </>
            )}
          </button>
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow-xs border border-gray-200">
          <div className="px-4 py-3 border-b border-gray-200 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-600">
            <span>Last generated: <span className="font-medium text-gray-800">{formatIst(rec.generated_at)}</span></span>
            <span>Model: <span className="font-medium text-gray-800">{rec.model}</span></span>
            <span>Provider: <span className="font-medium text-gray-800">{rec.provider}</span></span>
            <span>Nodes analyzed: <span className="font-medium text-gray-800">{rec.node_count}</span></span>
          </div>
          <div className="p-4 text-sm text-gray-900">
            <pre className="whitespace-pre-wrap font-sans">{rec.content}</pre>
          </div>
        </div>
      )}
    </div>
  )
}
