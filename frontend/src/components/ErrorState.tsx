export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <p className="text-red-600 font-medium">{message}</p>
      {retry && (
        <button
          onClick={retry}
          className="mt-4 px-4 py-2 bg-brand-600 text-white text-sm rounded hover:bg-brand-700"
        >
          Retry
        </button>
      )}
    </div>
  )
}
