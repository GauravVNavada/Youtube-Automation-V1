import { create } from "zustand";
import { persist } from "zustand/middleware";
import { defaultSettings, type MusicSource, type PlaygroundMusicUpload, type PlaygroundSettings } from "../types";

type PlaygroundState = {
  activeRunId: string;
  selectedStageId: string;
  selectedMusicId: string;
  musicSource: MusicSource;
  uploadedMusic: PlaygroundMusicUpload | null;
  messageDraft: string;
  settings: PlaygroundSettings;
  setActiveRunId: (id: string) => void;
  setSelectedStageId: (id: string) => void;
  setSelectedMusicId: (id: string) => void;
  setMusicSource: (source: MusicSource) => void;
  setUploadedMusic: (music: PlaygroundMusicUpload | null) => void;
  setMessageDraft: (value: string) => void;
  updateSettings: (patch: Partial<PlaygroundSettings>) => void;
  resetSettings: () => void;
};

export const usePlaygroundStore = create<PlaygroundState>()(
  persist(
    (set) => ({
      activeRunId: "",
      selectedStageId: "",
      selectedMusicId: "",
      musicSource: "template",
      uploadedMusic: null,
      messageDraft: "",
      settings: defaultSettings,
      setActiveRunId: (id) => set({ activeRunId: id }),
      setSelectedStageId: (id) => set({ selectedStageId: id }),
      setSelectedMusicId: (id) => set({ selectedMusicId: id }),
      setMusicSource: (source) => set({ musicSource: source }),
      setUploadedMusic: (music) => set({ uploadedMusic: music }),
      setMessageDraft: (value) => set({ messageDraft: value }),
      updateSettings: (patch) =>
        set((state) => ({
          settings: { ...state.settings, ...patch }
        })),
      resetSettings: () => set({ settings: defaultSettings, selectedMusicId: "", musicSource: "template", uploadedMusic: null })
    }),
    {
      name: "modular-shorts-playground"
    }
  )
);
