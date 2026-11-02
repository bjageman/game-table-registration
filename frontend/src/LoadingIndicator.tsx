export default function LoadingIndicator({ label }: { label: string }) {
  return <span className="loading-indicator" role="status">
    <span className="loader" aria-hidden="true" />
    <span>{label}</span>
  </span>;
}
