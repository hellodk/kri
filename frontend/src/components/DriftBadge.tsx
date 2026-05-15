function severityColour(score: number): string {
  if (score <= 5) return 'bg-green-100 text-green-800'
  if (score <= 20) return 'bg-blue-100 text-blue-800'
  if (score <= 50) return 'bg-yellow-100 text-yellow-800'
  if (score <= 80) return 'bg-orange-100 text-orange-800'
  return 'bg-red-100 text-red-800'
}

export function DriftBadge({ score }: { score: number }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium tabular-nums ${severityColour(score)}`}>
      {score}
    </span>
  )
}
