import Link from "next/link";
import { Job } from "@/lib/types";
import { dateTime, number, statusLabels } from "@/lib/format";
export function ErrorBox({ error }: { error?: string }) {
  return error ? (
    <div className="error" role="alert">
      {error}
    </div>
  ) : null;
}
export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}
export function Stat({
  label,
  value,
  detail,
}: {
  label: string;
  value: React.ReactNode;
  detail?: React.ReactNode;
}) {
  return (
    <div className="stat">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}
export function Badge({ status }: { status: string }) {
  return (
    <span className={"badge " + status}>{statusLabels[status] || status}</span>
  );
}
export function JobsTable({ jobs }: { jobs: Job[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>実行日時</th>
            <th>処理 / 分析期間</th>
            <th>条件</th>
            <th>状態</th>
            <th>完了日時</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id}>
              <td>{dateTime(j.created_at)}</td>
              <td>
                {j.kind === "update"
                  ? "市場データ更新"
                  : j.config.start_date + " → " + j.config.end_date}
              </td>
              <td>
                {j.kind === "update"
                  ? j.config.tickers?.length
                    ? number(j.config.tickers.length) + "銘柄"
                    : "全市場"
                  : number(
                      j.config.drawdown_thresholds.length *
                        j.config.volume_ratio_thresholds.length,
                    ) +
                    "条件 / " +
                    j.config.holding_periods.join(", ") +
                    "日"}
              </td>
              <td>
                <Badge status={j.status} />
              </td>
              <td>{dateTime(j.completed_at)}</td>
              <td>
                <Link href={"/backtests/" + j.id}>開く ↗</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function Notice() {
  return (
    <aside className="notice">
      <strong>Survivorship Bias</strong>{" "}
      現在上場している国内普通株のみを対象とし、倒産・上場廃止銘柄を含みません。市場区分は現在の属性です。無料データの欠損・補正制約があり、結果はEvent
      Studyとして確認してください。
    </aside>
  );
}
