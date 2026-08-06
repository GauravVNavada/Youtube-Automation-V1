import { RefreshCw } from "lucide-react";
import type { RunSummary } from "../types";
import { formatDate } from "../utils/format";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

type RunHistoryProps = {
  runs: RunSummary[];
  activeRunId: string;
  onSelect: (id: string) => void;
  onRefresh: () => void;
};

export function RunHistory({ runs, activeRunId, onSelect, onRefresh }: RunHistoryProps) {
  return (
    <Card className="rounded-none border-x-0 border-b-0 border-slate-200 shadow-none dark:border-slate-800">
      <CardHeader className="border-b border-slate-200 dark:border-slate-800">
        <div>
          <span className="mb-1 block text-xs font-bold uppercase text-slate-500">Recent</span>
          <CardTitle>Runs</CardTitle>
        </div>
        <Button variant="ghost" size="icon" aria-label="Refresh runs" title="Refresh runs" onClick={onRefresh}>
          <RefreshCw className="h-4 w-4" />
        </Button>
      </CardHeader>

      <CardContent className="pt-5">
        <div className="grid gap-2">
          {runs.map((run) => (
            <button
              className={`grid min-h-14 w-full grid-cols-[12px_minmax(0,1fr)] items-center gap-3 rounded-md border bg-white p-3 text-left shadow-sm transition dark:bg-slate-900 ${
                run.id === activeRunId ? "border-cyan-700 shadow-[inset_3px_0_0_#0e7490]" : "border-slate-200 hover:border-cyan-500 dark:border-slate-800"
              }`}
              type="button"
              key={run.id}
              onClick={() => onSelect(run.id)}
            >
              <span
                className={`h-2.5 w-2.5 rounded-full ${
                  run.status === "succeeded"
                    ? "bg-emerald-700"
                    : run.status === "failed"
                      ? "bg-red-700"
                      : run.status === "running"
                        ? "bg-amber-400"
                        : "bg-slate-300"
                }`}
              />
              <span className="min-w-0">
                <strong className="block truncate text-sm text-slate-950 dark:text-slate-50">{run.user_message || "Untitled run"}</strong>
                <small className="mt-0.5 block text-xs text-slate-500">
                  {run.status} · {formatDate(run.updated_at || run.created_at)}
                </small>
              </span>
            </button>
          ))}
          {!runs.length ? <div className="grid min-h-20 place-items-center rounded-md border border-dashed border-slate-300 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">No runs yet.</div> : null}
        </div>
      </CardContent>
    </Card>
  );
}
