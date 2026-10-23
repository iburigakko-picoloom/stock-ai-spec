export function SaveProgress({ label = "端末に保存中…" }: { label?: string }) {
  return <div className="save-progress" role="status" aria-live="polite">
    <span className="save-progress-spinner" aria-hidden="true" />
    <span>{label}<small>完了が表示されるまでお待ちください。</small></span>
  </div>;
}
