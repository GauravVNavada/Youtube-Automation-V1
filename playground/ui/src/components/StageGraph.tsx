import type { Stage } from "../types";
import { titleize } from "../utils/format";

type StageGraphProps = {
  stages: Stage[];
  selectedStageId: string;
  onSelect: (stage: Stage) => void;
};

type NodeLayout = {
  stage: Stage;
  index: number;
  x: number;
  y: number;
  row: number;
  col: number;
};

const width = 1280;
const height = 640;
const cardW = 238;
const cardH = 98;
const marginX = 56;
const marginY = 80;

export function StageGraph({ stages, selectedStageId, onSelect }: StageGraphProps) {
  const nodes = layoutNodes(stages);
  const rows = Math.max(1, Math.max(...nodes.map((node) => node.row), 0) + 1);
  const stoppedNodeId = [...nodes].reverse().find((node) => isErrorStatus(node.stage.status))?.stage.id || "";

  return (
    <section className="relative h-full min-h-0 overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950" aria-label="AWS-style agent pipeline">
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Agent pipeline graph" preserveAspectRatio="xMidYMid meet">
        <defs>
          <marker id="aws-edge-arrow-slate" markerHeight="9" markerWidth="11" orient="auto" refX="10" refY="4.5">
            <path d="M0,0 L11,4.5 L0,9 z" className="fill-slate-500 dark:fill-slate-500" />
          </marker>
          <marker id="aws-edge-arrow-green" markerHeight="9" markerWidth="11" orient="auto" refX="10" refY="4.5">
            <path d="M0,0 L11,4.5 L0,9 z" className="fill-emerald-500 dark:fill-emerald-700" />
          </marker>
          <marker id="aws-edge-arrow-red" markerHeight="9" markerWidth="11" orient="auto" refX="10" refY="4.5">
            <path d="M0,0 L11,4.5 L0,9 z" className="fill-red-500 dark:fill-red-700" />
          </marker>
          <marker id="aws-edge-arrow-amber" markerHeight="9" markerWidth="11" orient="auto" refX="10" refY="4.5">
            <path d="M0,0 L11,4.5 L0,9 z" className="fill-amber-400 dark:fill-amber-700" />
          </marker>
          <filter id="aws-card-shadow" x="-20%" y="-35%" width="140%" height="180%">
            <feDropShadow dx="0" dy="8" stdDeviation="9" floodOpacity="0.12" />
          </filter>
        </defs>

        <rect width={width} height={height} rx="18" className="fill-slate-50 dark:fill-slate-950" />
        <path d="M 28 46 H 1252" className="stroke-slate-200 dark:stroke-slate-800" />

        {Array.from({ length: rows }).map((_, row) => (
          <g key={`lane-${row}`}>
            <rect x="34" y={laneTop(row, rows)} width="1212" height={laneHeight(rows)} rx="18" className="fill-white/70 stroke-slate-200 dark:fill-slate-900/20 dark:stroke-slate-800" />
            <text x="54" y={laneTop(row, rows) + 25} className="fill-slate-500 text-[12px] font-black uppercase tracking-wide dark:fill-slate-400">
              Phase {row + 1}
            </text>
          </g>
        ))}

        {nodes.slice(0, -1).map((node, index) => {
          const next = nodes[index + 1];
          return <path d={edgePath(node, next)} className={`fill-none stroke-[3] ${edgeClass(node, next, stoppedNodeId)}`} markerEnd={`url(#${edgeMarker(node, next, stoppedNodeId)})`} key={`${node.stage.id}-${next.stage.id}`} />;
        })}

        {nodes.map((node) => {
          const selected = node.stage.id === selectedStageId;
          const isStopped = node.stage.id === stoppedNodeId;
          const palette = nodePalette(node.stage.status, selected, isStopped);
          const title = splitLabel(titleize(node.stage.agent_name), 15);
          return (
            <g className="cursor-pointer outline-none" key={node.stage.id} role="button" tabIndex={0} onClick={() => onSelect(node.stage)} onKeyDown={(event) => event.key === "Enter" && onSelect(node.stage)}>
              {isStopped ? (
                <g>
                  <rect x={node.x + cardW - 112} y={node.y - 32} width="112" height="24" rx="12" className="fill-red-700 dark:fill-red-600" />
                  <text x={node.x + cardW - 56} y={node.y - 15} textAnchor="middle" className="fill-white text-[12px] font-black uppercase">
                    stopped here
                  </text>
                </g>
              ) : null}
              <rect x={node.x} y={node.y} width={cardW} height={cardH} rx="16" className={`${palette.card} ${selected ? "stroke-[4]" : "stroke-[2]"}`} filter="url(#aws-card-shadow)" />
              <rect x={node.x + 16} y={node.y + 18} width="44" height="44" rx="11" className={palette.iconBg} />
              <text x={node.x + 38} y={node.y + 47} textAnchor="middle" className={palette.iconText}>
                {node.index + 1}
              </text>
              <text x={node.x + 74} y={node.y + 31} className="fill-slate-950 text-[15px] font-black dark:fill-white">
                {title.map((line, lineIndex) => (
                  <tspan x={node.x + 74} dy={lineIndex === 0 ? 0 : 17} key={line}>
                    {line}
                  </tspan>
                ))}
              </text>
              <rect x={node.x + 74} y={node.y + 66} width={statusWidth(node.stage.status)} height="20" rx="10" className={palette.statusBg} />
              <circle cx={node.x + 87} cy={node.y + 76} r="4" className={palette.statusDot} />
              <text x={node.x + 99} y={node.y + 81} className={palette.statusText}>
                {node.stage.status}
              </text>
            </g>
          );
        })}
      </svg>

      {!stages.length ? <div className="absolute inset-0 grid place-items-center text-sm text-slate-500 dark:text-slate-400">No agent nodes yet.</div> : null}
    </section>
  );
}

function layoutNodes(stages: Stage[]): NodeLayout[] {
  const count = stages.length;
  if (!count) return [];
  const columns = count <= 4 ? count : 4;
  const rows = Math.ceil(count / columns);
  const usableW = width - marginX * 2 - cardW;
  const usableH = height - marginY * 2 - cardH;
  const gapX = columns <= 1 ? 0 : usableW / (columns - 1);
  const gapY = rows <= 1 ? 0 : usableH / (rows - 1);

  return stages.map((stage, index) => {
    const row = Math.floor(index / columns);
    const columnInRow = index % columns;
    const col = row % 2 === 1 ? columns - 1 - columnInRow : columnInRow;
    return {
      stage,
      index,
      row,
      col,
      x: marginX + col * gapX,
      y: marginY + row * gapY
    };
  });
}

function edgePath(from: NodeLayout, to: NodeLayout) {
  const sameRowReverse = from.row === to.row && to.x < from.x;
  const startX = sameRowReverse ? from.x : from.x + cardW;
  const startY = from.y + cardH / 2;
  const endX = sameRowReverse ? to.x + cardW : to.x;
  const endY = to.y + cardH / 2;
  const midX = (startX + endX) / 2;
  const rowChange = from.row !== to.row;

  if (!rowChange) {
    const inset = sameRowReverse ? 10 : -10;
    return `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX + inset} ${endY}`;
  }

  const dropX = from.row % 2 === 0 ? from.x + cardW / 2 : from.x + cardW / 2;
  const nextY = to.y + cardH / 2;
  return `M ${from.x + cardW / 2} ${from.y + cardH} C ${dropX} ${from.y + cardH + 42}, ${to.x + cardW / 2} ${nextY - 42}, ${to.x + cardW / 2} ${to.y - 8}`;
}

function laneTop(row: number, rows: number) {
  const laneGap = 12;
  const available = height - 74 - laneGap * (rows - 1);
  return 54 + row * (available / rows + laneGap);
}

function laneHeight(rows: number) {
  const laneGap = 12;
  return (height - 74 - laneGap * (rows - 1)) / rows;
}

function splitLabel(label: string, maxLength: number) {
  const words = label.split(" ");
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (next.length > maxLength && current) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
    if (lines.length === 2) break;
  }
  if (current && lines.length < 2) lines.push(current);
  return lines.length ? lines : [label];
}

function statusWidth(status: string) {
  return Math.max(82, Math.min(118, status.length * 8 + 30));
}

function nodePalette(status: string, selected: boolean, isStopped: boolean) {
  if (isErrorStatus(status)) {
    return {
      card: `${isStopped || selected ? "fill-red-50 stroke-red-700 dark:fill-red-950 dark:stroke-red-500" : "fill-white stroke-red-300 dark:fill-slate-950 dark:stroke-red-900"}`,
      iconBg: "fill-red-700 dark:fill-red-600",
      iconText: "fill-white text-[18px] font-black",
      statusBg: "fill-red-100 dark:fill-red-950",
      statusDot: "fill-red-700 dark:fill-red-400",
      statusText: "fill-red-800 text-[12px] font-bold dark:fill-red-100"
    };
  }
  if (isSuccessStatus(status)) {
    return {
      card: selected ? "fill-emerald-50 stroke-emerald-700 dark:fill-emerald-950 dark:stroke-emerald-400" : "fill-white stroke-emerald-300 dark:fill-slate-950 dark:stroke-emerald-800",
      iconBg: "fill-emerald-700 dark:fill-emerald-600",
      iconText: "fill-white text-[18px] font-black",
      statusBg: "fill-emerald-100 dark:fill-emerald-950",
      statusDot: "fill-emerald-700 dark:fill-emerald-400",
      statusText: "fill-emerald-800 text-[12px] font-bold dark:fill-emerald-100"
    };
  }
  if (status === "running") {
    return {
      card: selected ? "fill-amber-50 stroke-amber-600 dark:fill-amber-950 dark:stroke-amber-400" : "fill-white stroke-amber-200 dark:fill-slate-950 dark:stroke-amber-800",
      iconBg: "fill-amber-100 dark:fill-amber-900",
      iconText: "fill-amber-950 text-[18px] font-black dark:fill-amber-100",
      statusBg: "fill-amber-100 dark:fill-amber-900",
      statusDot: "fill-amber-500",
      statusText: "fill-amber-800 text-[12px] font-bold dark:fill-amber-100"
    };
  }
  return {
    card: selected ? "fill-cyan-50 stroke-cyan-600 dark:fill-cyan-950 dark:stroke-cyan-400" : "fill-white stroke-slate-200 dark:fill-slate-950 dark:stroke-slate-800",
    iconBg: "fill-slate-100 dark:fill-slate-900",
    iconText: "fill-cyan-700 text-[18px] font-black dark:fill-cyan-200",
    statusBg: "fill-slate-100 dark:fill-slate-900",
    statusDot: "fill-cyan-600 dark:fill-cyan-300",
    statusText: "fill-slate-600 text-[12px] font-bold dark:fill-slate-300"
  };
}

function edgeClass(from: NodeLayout, to: NodeLayout, stoppedNodeId: string) {
  if (to.stage.id === stoppedNodeId || isErrorStatus(to.stage.status)) return "stroke-red-500 dark:stroke-red-700";
  if (isSuccessStatus(from.stage.status) && isSuccessStatus(to.stage.status)) return "stroke-emerald-400 dark:stroke-emerald-700";
  if (from.stage.status === "running" || to.stage.status === "running") return "stroke-amber-400 dark:stroke-amber-700";
  return "stroke-slate-400 dark:stroke-slate-600";
}

function edgeMarker(from: NodeLayout, to: NodeLayout, stoppedNodeId: string) {
  if (to.stage.id === stoppedNodeId || isErrorStatus(to.stage.status)) return "aws-edge-arrow-red";
  if (isSuccessStatus(from.stage.status) && isSuccessStatus(to.stage.status)) return "aws-edge-arrow-green";
  if (from.stage.status === "running" || to.stage.status === "running") return "aws-edge-arrow-amber";
  return "aws-edge-arrow-slate";
}

function isSuccessStatus(status: string) {
  return ["succeeded", "success", "completed", "complete"].includes(status.toLowerCase());
}

function isErrorStatus(status: string) {
  return ["failed", "failure", "error", "errored", "stopped", "cancelled", "canceled"].includes(status.toLowerCase());
}
