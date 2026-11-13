import { DEFAULT_MONACO_OPTIONS, SupportedLanguage } from "@/lib/sandbox";

export const EDITOR_SETTINGS_STORAGE_KEY = "codepilot_editor_settings";

export interface EditorSettings {
  fontSize: number;
  tabSize: 2 | 4;
  wordWrap: "off" | "on";
  minimap: boolean;
  defaultLanguage: SupportedLanguage;
}

export const DEFAULT_EDITOR_SETTINGS: EditorSettings = {
  fontSize: 13,
  tabSize: 4,
  wordWrap: "off",
  minimap: false,
  defaultLanguage: "python",
};

const VALID_FONT_SIZES = [12, 13, 14, 15, 16, 18];

function isValidLanguage(lang: unknown): lang is SupportedLanguage {
  return lang === "python" || lang === "java" || lang === "cpp";
}

export function getEditorSettings(): EditorSettings {
  if (typeof window === "undefined") {
    return DEFAULT_EDITOR_SETTINGS;
  }

  try {
    const raw = localStorage.getItem(EDITOR_SETTINGS_STORAGE_KEY);
    if (!raw) return DEFAULT_EDITOR_SETTINGS;

    const parsed = JSON.parse(raw) as Partial<EditorSettings>;
    return {
      fontSize:
        typeof parsed.fontSize === "number" && VALID_FONT_SIZES.includes(parsed.fontSize)
          ? parsed.fontSize
          : DEFAULT_EDITOR_SETTINGS.fontSize,
      tabSize: parsed.tabSize === 2 || parsed.tabSize === 4 ? parsed.tabSize : DEFAULT_EDITOR_SETTINGS.tabSize,
      wordWrap: parsed.wordWrap === "on" || parsed.wordWrap === "off" ? parsed.wordWrap : DEFAULT_EDITOR_SETTINGS.wordWrap,
      minimap: typeof parsed.minimap === "boolean" ? parsed.minimap : DEFAULT_EDITOR_SETTINGS.minimap,
      defaultLanguage: isValidLanguage(parsed.defaultLanguage)
        ? parsed.defaultLanguage
        : DEFAULT_EDITOR_SETTINGS.defaultLanguage,
    };
  } catch {
    return DEFAULT_EDITOR_SETTINGS;
  }
}

export function saveEditorSettings(settings: EditorSettings): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(EDITOR_SETTINGS_STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Ignore storage quota errors
  }
}

export function resetEditorSettings(): EditorSettings {
  saveEditorSettings(DEFAULT_EDITOR_SETTINGS);
  return DEFAULT_EDITOR_SETTINGS;
}

export function buildMonacoOptions(settings: EditorSettings, extra?: { readOnly?: boolean }) {
  return {
    ...DEFAULT_MONACO_OPTIONS,
    fontSize: settings.fontSize,
    tabSize: settings.tabSize,
    wordWrap: settings.wordWrap,
    minimap: { enabled: settings.minimap },
    ...(extra?.readOnly !== undefined ? { readOnly: extra.readOnly } : {}),
  };
}

