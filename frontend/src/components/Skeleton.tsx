export function Skeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4">
      {/* Static placeholder array — no stable identity; index key is safe here */}
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-10 bg-gray-200 rounded animate-pulse" />
      ))}
    </div>
  )
}
