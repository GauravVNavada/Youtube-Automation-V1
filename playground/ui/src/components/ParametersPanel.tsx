import { RotateCcw } from "lucide-react";
import type { PlaygroundSettings } from "../types";
import { formatPercent } from "../utils/format";
import { Button } from "./ui/button";
import { Checkbox } from "./ui/checkbox";
import { Field, Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

type ParametersPanelProps = {
  settings: PlaygroundSettings;
  onChange: (patch: Partial<PlaygroundSettings>) => void;
  onReset: () => void;
};

export function ParametersPanel({ settings, onChange, onReset }: ParametersPanelProps) {
  return (
    <div className="grid gap-4 p-4">
      <section className="grid gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="block text-xs font-bold uppercase text-slate-500">Generation</span>
            <strong className="text-sm text-slate-950 dark:text-slate-50">Script and asset controls</strong>
          </div>
          <Button variant="ghost" size="sm" onClick={onReset}>
            <RotateCcw className="h-4 w-4" />
            Reset
          </Button>
        </div>

        <Field>
          <Label>Duration</Label>
          <div className="grid grid-cols-3 gap-2">
            {[30, 45, 60].map((value) => (
              <Button key={value} variant={settings.duration === value ? "default" : "secondary"} onClick={() => onChange({ duration: value })}>
                {value}s
              </Button>
            ))}
          </div>
        </Field>

        <RangeField label="Caption words" value={settings.caption_words} min={1} max={8} step={1} suffix="words" onChange={(caption_words) => onChange({ caption_words })} />
        <RangeField label="Images" value={settings.image_count} min={1} max={24} step={1} suffix="assets" onChange={(image_count) => onChange({ image_count })} />
        <RangeField label="Voice speed" value={settings.voice_speed} min={0.65} max={1.4} step={0.01} suffix="x" onChange={(voice_speed) => onChange({ voice_speed })} />
        <RangeField label="Music volume" value={settings.music_volume} min={0} max={0.8} step={0.01} display={formatPercent(settings.music_volume)} onChange={(music_volume) => onChange({ music_volume })} />
      </section>

      <section className="grid gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900">
        <div>
          <span className="block text-xs font-bold uppercase text-slate-500">Render</span>
          <strong className="text-sm text-slate-950 dark:text-slate-50">Visual motion and transition controls</strong>
        </div>

        <label className="flex items-center justify-between gap-3 rounded-md border border-slate-200 bg-white p-3 text-sm font-semibold dark:border-slate-800 dark:bg-slate-950">
          <span>Visual motion</span>
          <Checkbox checked={settings.visual_motion} onCheckedChange={(checked) => onChange({ visual_motion: checked === true })} />
        </label>

        <SelectField
          label="Transition"
          value={settings.transition_style}
          onValueChange={(transition_style) => onChange({ transition_style: transition_style as PlaygroundSettings["transition_style"] })}
          options={["slide", "fade", "wipe", "cut"]}
        />
        <SelectField
          label="Zoom"
          value={settings.zoom_variant}
          onValueChange={(zoom_variant) => onChange({ zoom_variant: zoom_variant as PlaygroundSettings["zoom_variant"] })}
          options={["mixed", "center_in", "center_out", "still"]}
        />
        <RangeField label="Transition time" value={settings.transition_seconds} min={0} max={1.2} step={0.05} suffix="s" onChange={(transition_seconds) => onChange({ transition_seconds })} />
        <RangeField label="Min visual segment" value={settings.min_visual_segment_ms} min={1200} max={8000} step={100} suffix="ms" onChange={(min_visual_segment_ms) => onChange({ min_visual_segment_ms })} />
      </section>
    </div>
  );
}

function RangeField({
  label,
  value,
  min,
  max,
  step,
  suffix = "",
  display,
  onChange
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix?: string;
  display?: string;
  onChange: (value: number) => void;
}) {
  return (
    <Field>
      <div className="flex items-center justify-between gap-3">
        <Label>{label}</Label>
        <span className="text-xs font-bold text-cyan-800 dark:text-cyan-300">
          {display || `${value}${suffix ? ` ${suffix}` : ""}`}
        </span>
      </div>
      <input className="h-2 w-full accent-cyan-700" type="range" min={min} max={max} step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} />
    </Field>
  );
}

function SelectField({ label, value, options, onValueChange }: { label: string; value: string; options: string[]; onValueChange: (value: string) => void }) {
  return (
    <Field>
      <Label>{label}</Label>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {option.replaceAll("_", " ")}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );
}
