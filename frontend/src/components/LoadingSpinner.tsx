export default function LoadingSpinner({ text = 'Loading...' }: { text?: string }) {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="flex items-center gap-3">
        <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-indigo-600" />
        <span className="text-sm text-gray-500">{text}</span>
      </div>
    </div>
  )
}
