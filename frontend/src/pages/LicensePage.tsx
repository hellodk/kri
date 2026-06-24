import { useQuery } from '@tanstack/react-query'
import { sbomApi, type LicenseSummary } from '../api/sbom'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'

export function LicensePage() {
  const { data, isLoading, error, refetch } = useQuery<LicenseSummary>({
    queryKey: ['license-summary'],
    queryFn: () => sbomApi.getLicenseSummary(),
    refetchInterval: 5 * 60 * 1000, // 5 minutes
  })

  if (isLoading) return <div className="p-6"><Skeleton rows={12} /></div>

  if (error) {
    return <ErrorState message="Failed to load license data" retry={refetch} />
  }

  if (!data) {
    return (
      <div className="p-6 text-center text-gray-500">
        <p>No license data available</p>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 mb-2">License Compliance</h1>
        <p className="text-gray-500">
          Track copyleft and unknown license usage across your fleet
        </p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 border-l-4 border-l-amber-500 p-5 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Copyleft Packages</p>
          <p className="text-4xl font-black tabular-nums text-amber-700">{data.copyleft_count}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 border-l-4 border-l-gray-400 p-5 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Unknown Licenses</p>
          <p className="text-4xl font-black tabular-nums text-gray-700">{data.unknown_license_count}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 border-l-4 border-l-emerald-500 p-5 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Unique Licenses</p>
          <p className="text-4xl font-black tabular-nums text-emerald-700">{data.total_distinct_licenses}</p>
        </div>
      </div>

      {/* Copyleft Risk Section */}
      <div className="bg-white rounded-xl border border-gray-200 border-l-4 border-l-amber-500 shadow-sm p-6">
        <div className="flex items-center gap-3 mb-4">
          <h2 className="text-xl font-semibold text-gray-900">Copyleft Risk</h2>
          <span className="ml-auto px-3 py-1 bg-amber-100 text-amber-700 rounded text-sm font-medium">
            {data.copyleft_count} packages
          </span>
        </div>

        {data.copyleft_packages.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th scope="col" className="text-left px-4 py-3 text-gray-500 font-semibold">Package</th>
                  <th scope="col" className="text-left px-4 py-3 text-gray-500 font-semibold">Version</th>
                  <th scope="col" className="text-left px-4 py-3 text-gray-500 font-semibold">License</th>
                  <th scope="col" className="text-left px-4 py-3 text-gray-500 font-semibold">Node ID</th>
                </tr>
              </thead>
              <tbody>
                {data.copyleft_packages.map((pkg, i) => (
                  <tr key={`${pkg.name}-${pkg.license}-${i}`} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3 text-gray-900 font-mono text-xs break-all">{pkg.name}</td>
                    <td className="px-4 py-3 text-gray-500">{pkg.version || '—'}</td>
                    <td className="px-4 py-3">
                      <span className="inline-block px-2.5 py-1 bg-amber-100 text-amber-700 rounded text-xs font-semibold">
                        {pkg.license}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 font-mono text-xs">{pkg.node_id.slice(0, 8)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-8 text-center text-gray-500">
            <p>No copyleft licenses detected</p>
          </div>
        )}
      </div>

      {/* Unknown Licenses Section */}
      <div className="bg-white rounded-xl border border-gray-200 border-l-4 border-l-gray-400 shadow-sm p-6">
        <div className="flex items-center gap-3 mb-4">
          <h2 className="text-xl font-semibold text-gray-900">Unknown Licenses</h2>
          <span className="ml-auto px-3 py-1 bg-gray-100 text-gray-600 rounded text-sm font-medium">
            {data.unknown_license_count} packages
          </span>
        </div>

        {data.unknown_license_count > 0 ? (
          <p className="text-gray-500 text-sm">
            {data.unknown_license_count} package{data.unknown_license_count !== 1 ? 's' : ''} with no license information. Review and license these components.
          </p>
        ) : (
          <div className="py-8 text-center text-gray-500">
            <p>All packages have license information</p>
          </div>
        )}
      </div>

      {/* License Distribution Section */}
      <div className="bg-white rounded-xl border border-gray-200 border-l-4 border-l-brand-600 shadow-sm p-6">
        <div className="flex items-center gap-3 mb-4">
          <h2 className="text-xl font-semibold text-gray-900">License Distribution</h2>
          <span className="ml-auto px-3 py-1 bg-blue-100 text-blue-700 rounded text-sm font-medium">
            {data.total_distinct_licenses} unique
          </span>
        </div>

        {data.top_licenses.length > 0 ? (
          <div className="space-y-3">
            {data.top_licenses.map(({ license, count }) => (
              <div key={license} className="flex items-center justify-between">
                <div className="flex items-center gap-3 flex-1">
                  <span className="font-mono text-sm text-gray-900">{license}</span>
                  <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden max-w-sm">
                    <div
                      className="h-full bg-gradient-to-r from-blue-600 to-blue-500"
                      style={{
                        width: `${(count / Math.max(...data.top_licenses.map((l) => l.count))) * 100}%`,
                      }}
                    ></div>
                  </div>
                </div>
                <span className="text-sm font-semibold text-gray-500 ml-4">{count}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="py-8 text-center text-gray-500">
            <p>No license data available</p>
          </div>
        )}
      </div>
    </div>
  )
}
