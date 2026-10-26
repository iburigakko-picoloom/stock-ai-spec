import { Link, useParams } from "react-router-dom";
import { PageHeader } from "../components";
import { CurrentAccountPanel } from "../mobile/CurrentAccountPanel";

export function AssetManagementPage() {
  const { section } = useParams();
  return <div className="page"><Link className="back-link" to={section ? "/assets" : "/"}>← 戻る</Link>
    <PageHeader title={section === "cash" ? "現金残高の変更" : "資産管理"} />
    {section === "cash" ? <CurrentAccountPanel mode="cash" /> : <nav className="compact-links" aria-label="資産の管理">
      <Link className="button button--secondary" to="/holdings">資産登録・保有修正</Link>
      <Link className="button button--secondary" to="/assets/cash">現金残高の変更</Link>
      <Link className="button button--secondary" to="/assets/history">残高・修正履歴</Link>
      <Link className="button button--secondary" to="/today/executions">取引を記録</Link>
      <Link className="button button--secondary" to="/transactions">取引履歴</Link>
    </nav>}
  </div>;
}
