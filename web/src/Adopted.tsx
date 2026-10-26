import type { ReactNode } from "react";

export function Field({ label, children, hint }: { label:string; children:ReactNode; hint?:ReactNode }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small className="subhint">{hint}</small>}</label>;
}
export function KV({ label, value }: { label:ReactNode; value:ReactNode }) {
  return <div className="subrow"><span>{label}</span><strong>{value}</strong></div>;
}
export function SettingGroup({ title, number, children }: {title:string;number?:string;children:ReactNode}) {
  return <section className="ss-group">{number && <div className="ss-section-number">{number}</div>}<h3>{title}</h3><div className="stack">{children}</div></section>;
}
export function FormGroup({title,children}:{title:string;children:ReactNode}) {
  return <section className="subrow form-section"><h3 className="section-title">{title}</h3><div className="subgrid">{children}</div></section>;
}
