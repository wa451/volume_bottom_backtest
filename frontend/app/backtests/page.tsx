"use client";
import { useState } from "react";
import Link from "next/link";
import { useApi } from "@/lib/api";
import { Page, Job } from "@/lib/types";
import { ErrorBox, JobsTable, Empty } from "@/components/common";
export default function History() {
  const [offset, setOffset] = useState(0);
  const { data, error, loading } = useApi<Page<Job>>(
    "backtests?limit=30&offset=" + offset,
    5000,
  );
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">RUN ARCHIVE</div>
          <h1>検証履歴</h1>
          <p className="subtitle">
            保存した設定と結果をいつでも再確認できます。
          </p>
        </div>
        <Link className="button primary" href="/backtest/new">
          ＋ 新規検証
        </Link>
      </div>
      <ErrorBox error={error} />
      <div className="panel">
        {data?.items.length ? (
          <JobsTable jobs={data.items} />
        ) : (
          <Empty>
            {loading ? "読み込み中…" : "バックテスト履歴がありません。"}
          </Empty>
        )}
        <div className="pagination">
          <button disabled={!offset} onClick={() => setOffset(offset - 30)}>
            前へ
          </button>
          <span>
            {offset + 1}〜{Math.min(offset + 30, data?.total || 0)} /{" "}
            {data?.total || 0}
          </span>
          <button
            disabled={offset + 30 >= (data?.total || 0)}
            onClick={() => setOffset(offset + 30)}
          >
            次へ
          </button>
        </div>
      </div>
    </>
  );
}
