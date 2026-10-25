//! Per-model launch profiles persisted in the app config dir.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use crate::state::model::ModelId;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct QwenSettings {
    pub context: i64,
    pub mtp: i64,
    pub thinking: String,
    pub fast_start: bool,
    pub text_only: bool,
    pub no_async_scheduling: bool,
}

impl Default for QwenSettings {
    fn default() -> Self {
        Self {
            context: 262144,
            mtp: 3,
            thinking: "xhigh".into(),
            fast_start: true,
            text_only: true,
            no_async_scheduling: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct GlmSettings {
    pub context: i64,
    pub streams: i64,
    pub thinking: String,
    pub text_only: bool,
}

impl Default for GlmSettings {
    fn default() -> Self {
        Self {
            context: 262144,
            streams: 3,
            thinking: "low".into(),
            text_only: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct Settings {
    /// Optional explicit repo location (defaults to auto-detection).
    pub project_root: Option<String>,
    pub model: ModelId,
    pub keepalive_min: i64,
    pub qwen: QwenSettings,
    pub glm: GlmSettings,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            project_root: None,
            model: ModelId::Qwen38_27b,
            keepalive_min: 480,
            qwen: QwenSettings::default(),
            glm: GlmSettings::default(),
        }
    }
}

impl Settings {
    pub const CONTEXTS: [i64; 2] = [131072, 262144];
    pub const QWEN_THINKING_LEVELS: [&str; 3] = ["xhigh", "medium", "low"];
    pub const GLM_THINKING_LEVELS: [&str; 2] = ["high", "low"];

    pub fn validate(&self) -> Result<(), String> {
        if !(30..=540).contains(&self.keepalive_min) {
            return Err("Keepalive must be between 30 and 540 min (Kaggle caps TPU sessions at 9 h)".into());
        }

        match self.model {
            ModelId::Qwen38_27b => {
                if !Self::CONTEXTS.contains(&self.qwen.context) {
                    return Err("Qwen context must be 131072 or 262144".into());
                }
                if !(0..=5).contains(&self.qwen.mtp) {
                    return Err("Qwen MTP must be between 0 and 5".into());
                }
                if !Self::QWEN_THINKING_LEVELS.contains(&self.qwen.thinking.as_str()) {
                    return Err(format!(
                        "Qwen thinking must be one of: {}",
                        Self::QWEN_THINKING_LEVELS.join(", ")
                    ));
                }
            }
            ModelId::Glm53Flash => {
                if !Self::CONTEXTS.contains(&self.glm.context) {
                    return Err("GLM context must be 131072 or 262144".into());
                }
                if !(1..=3).contains(&self.glm.streams) {
                    return Err("GLM streams must be between 1 and 3".into());
                }
                if !Self::GLM_THINKING_LEVELS.contains(&self.glm.thinking.as_str()) {
                    return Err(format!(
                        "GLM thinking must be one of: {}",
                        Self::GLM_THINKING_LEVELS.join(", ")
                    ));
                }
            }
        }
        Ok(())
    }

    pub fn selected_context(&self) -> i64 {
        match self.model {
            ModelId::Qwen38_27b => self.qwen.context,
            ModelId::Glm53Flash => self.glm.context,
        }
    }

    pub fn selected_text_only(&self) -> bool {
        match self.model {
            ModelId::Qwen38_27b => self.qwen.text_only,
            ModelId::Glm53Flash => self.glm.text_only,
        }
    }

    /// Argument vector for `launch.py serve`. The launcher owns dataset defaults;
    /// the companion only supplies model/profile knobs it actually exposes.
    pub fn serve_args(&self) -> Vec<String> {
        let mut args = vec![
            "--model".into(),
            self.model.cli_id().into(),
            "--keepalive-min".into(),
            self.keepalive_min.to_string(),
        ];

        match self.model {
            ModelId::Qwen38_27b => {
                args.extend([
                    "--max-model-len".into(),
                    self.qwen.context.to_string(),
                    "--mtp".into(),
                    self.qwen.mtp.to_string(),
                    "--reasoning-effort".into(),
                    self.qwen.thinking.clone(),
                ]);
                if self.qwen.fast_start {
                    args.push("--fast-start".into());
                }
                if self.qwen.text_only {
                    args.push("--text-only".into());
                }
                if self.qwen.no_async_scheduling {
                    args.push("--no-async-scheduling".into());
                }
            }
            ModelId::Glm53Flash => {
                args.extend([
                    "--max-len".into(),
                    self.glm.context.to_string(),
                    "--streams".into(),
                    self.glm.streams.to_string(),
                    "--reasoning-effort".into(),
                    self.glm.thinking.clone(),
                ]);
                if self.glm.text_only {
                    args.push("--text-only".into());
                }
            }
        }
        args
    }

    fn file_path() -> Option<PathBuf> {
        dirs_config().map(|d| d.join("settings.json"))
    }

    pub fn load() -> Settings {
        Self::file_path()
            .map(|path| Self::load_from_path(&path))
            .unwrap_or_default()
    }

    /// Explicit path for isolated native persistence tests. Never changes the
    /// process-wide USERPROFILE/HOME or the user's actual settings file.
    pub(crate) fn load_from_path(path: &Path) -> Settings {
        std::fs::read_to_string(path)
            .ok()
            .and_then(|text| Self::from_json(&text))
            .unwrap_or_default()
    }

    fn from_json(text: &str) -> Option<Settings> {
        let value: Value = serde_json::from_str(text).ok()?;
        if value.get("qwen").is_some() || value.get("glm").is_some() || value.get("model").is_some() {
            let mut parsed: Settings = serde_json::from_value(value).ok()?;
            // The old companion permitted 4-8 GLM streams; at 262k the
            // current upstream engine has room for only three.
            if parsed.glm.streams > 3 {
                parsed.glm.streams = 3;
            }
            return Some(parsed);
        }

        // v0.3.2 and earlier stored one Qwen-only profile at the root. Preserve
        // every old field when upgrading to the dual-model schema.
        let mut out = Settings::default();
        out.project_root = value.get("projectRoot").and_then(Value::as_str).map(str::to_string);
        out.keepalive_min = value.get("keepaliveMin").and_then(Value::as_i64).unwrap_or(out.keepalive_min);
        out.qwen.context = value.get("context").and_then(Value::as_i64).unwrap_or(out.qwen.context);
        out.qwen.mtp = value.get("mtp").and_then(Value::as_i64).unwrap_or(out.qwen.mtp);
        out.qwen.thinking = value.get("thinking").and_then(Value::as_str).unwrap_or(&out.qwen.thinking).to_string();
        out.qwen.fast_start = value.get("fastStart").and_then(Value::as_bool).unwrap_or(out.qwen.fast_start);
        out.qwen.text_only = value.get("textOnly").and_then(Value::as_bool).unwrap_or(out.qwen.text_only);
        Some(out)
    }

    pub fn save(&self) -> Result<(), String> {
        let path = Self::file_path().ok_or("cannot resolve app config dir")?;
        self.save_to_path(&path)
    }

    /// Writes the same JSON as production, but allows a disposable test path.
    /// Stage beside the destination so an interrupted write cannot truncate the
    /// last good settings file. Rename is not a full power-loss durability guarantee.
    pub(crate) fn save_to_path(&self, path: &Path) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("cannot create config dir: {e}"))?;
        }
        let txt = serde_json::to_string_pretty(self)
            .map_err(|e| format!("cannot serialize settings: {e}"))?;
        let parent = path.parent().ok_or("cannot resolve config parent")?;
        let file_name = path.file_name().ok_or("cannot resolve config filename")?;

        // Exclusive creation prevents collisions with concurrent or interrupted
        // saves. Do not reuse or overwrite a stale temporary file after a crash.
        static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);
        let (mut file, temporary) = (0..32)
            .find_map(|_| {
                let serial = NEXT_TEMP.fetch_add(1, Ordering::Relaxed);
                let candidate = parent.join(format!(
                    ".{}.{}.{serial}.tmp",
                    file_name.to_string_lossy(),
                    std::process::id()
                ));
                match std::fs::OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(&candidate)
                {
                    Ok(file) => Some(Ok((file, candidate))),
                    Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => None,
                    Err(e) => Some(Err(format!("cannot stage settings: {e}"))),
                }
            })
            .ok_or_else(|| "cannot allocate a unique settings temporary file".to_string())??;

        let staged = file.write_all(txt.as_bytes()).and_then(|_| file.sync_all());
        drop(file); // Windows must release the writer before a rename/removal.
        let result = staged.and_then(|_| std::fs::rename(&temporary, path));
        if result.is_err() {
            let _ = std::fs::remove_file(&temporary);
        }
        result.map_err(|e| format!("cannot persist settings: {e}"))
    }
}

fn dirs_config() -> Option<PathBuf> {
    let home = std::env::var("USERPROFILE").or_else(|_| std::env::var("HOME")).ok()?;
    Some(PathBuf::from(home).join("AppData").join("Roaming").join("com.lucas.kaggle-tpu-companion"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct IsolatedSettingsPath {
        dir: PathBuf,
    }

    impl IsolatedSettingsPath {
        fn new() -> Self {
            static NEXT: AtomicUsize = AtomicUsize::new(0);
            let id = NEXT.fetch_add(1, Ordering::Relaxed);
            let dir = std::env::temp_dir().join(format!(
                "ktl-settings-test-{}-{id}",
                std::process::id()
            ));
            std::fs::create_dir(&dir).expect("create a fresh isolated test directory");
            Self { dir }
        }

        fn file(&self) -> PathBuf {
            self.dir.join("settings.json")
        }
    }

    impl Drop for IsolatedSettingsPath {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.dir);
        }
    }

    #[test]
    fn native_settings_save_and_reload_round_trip_without_user_profile() {
        let fixture = IsolatedSettingsPath::new();
        let mut saved = Settings::default();
        saved.model = ModelId::Glm53Flash;
        saved.keepalive_min = 210;
        saved.glm.streams = 2;
        saved.glm.thinking = "high".into();
        saved.glm.text_only = true;
        saved.qwen.mtp = 4;
        saved.validate().unwrap();
        saved.save_to_path(&fixture.file()).unwrap();

        let loaded = Settings::load_from_path(&fixture.file());
        assert_eq!(loaded.model, ModelId::Glm53Flash);
        assert_eq!(loaded.keepalive_min, 210);
        assert_eq!(loaded.glm.streams, 2);
        assert_eq!(loaded.glm.thinking, "high");
        assert!(loaded.glm.text_only);
        assert_eq!(loaded.qwen.mtp, 4);
        loaded.validate().unwrap();
    }

    #[test]
    fn native_settings_missing_or_invalid_file_falls_back_to_defaults() {
        let fixture = IsolatedSettingsPath::new();
        assert_eq!(Settings::load_from_path(&fixture.file()).keepalive_min, 480);
        std::fs::write(fixture.file(), b"{invalid json").unwrap();
        assert_eq!(Settings::load_from_path(&fixture.file()).keepalive_min, 480);
    }

    #[test]
    fn native_settings_replacement_preserves_complete_json_and_cleans_staging() {
        let fixture = IsolatedSettingsPath::new();
        let previous = Settings::default();
        previous.save_to_path(&fixture.file()).unwrap();

        let mut changed = previous.clone();
        changed.keepalive_min = 210;
        changed.model = ModelId::Glm53Flash;
        changed.glm.streams = 2;
        changed.save_to_path(&fixture.file()).unwrap();

        let raw = std::fs::read_to_string(fixture.file()).unwrap();
        let decoded: Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(decoded["keepaliveMin"], 210);
        assert_eq!(Settings::load_from_path(&fixture.file()).glm.streams, 2);
        assert_eq!(std::fs::read_dir(&fixture.dir).unwrap().count(), 1);
    }

    #[test]
    fn native_settings_failed_rename_cleans_staging_and_keeps_destination() {
        let fixture = IsolatedSettingsPath::new();
        // A directory cannot be replaced with a regular JSON file.
        std::fs::create_dir(fixture.file()).unwrap();
        assert!(Settings::default().save_to_path(&fixture.file()).is_err());
        assert!(fixture.file().is_dir());
        assert_eq!(std::fs::read_dir(&fixture.dir).unwrap().count(), 1);
    }

    #[cfg(windows)]
    #[test]
    fn native_settings_locked_destination_keeps_previous_json() {
        use std::os::windows::fs::OpenOptionsExt;

        let fixture = IsolatedSettingsPath::new();
        let previous = Settings::default();
        previous.save_to_path(&fixture.file()).unwrap();
        let original = std::fs::read(fixture.file()).unwrap();

        // FILE_SHARE_READ only: a second writer cannot acquire delete sharing
        // to replace this open destination on Windows.
        let lock = std::fs::OpenOptions::new()
            .read(true)
            .share_mode(0x00000001)
            .open(fixture.file())
            .unwrap();
        let mut changed = previous;
        changed.keepalive_min = 210;
        assert!(changed.save_to_path(&fixture.file()).is_err());
        drop(lock);
        assert_eq!(std::fs::read(fixture.file()).unwrap(), original);
        assert_eq!(std::fs::read_dir(&fixture.dir).unwrap().count(), 1);
    }

    #[test]
    fn defaults_keep_the_existing_qwen_profile() {
        let s = Settings::default();
        assert_eq!(s.model, ModelId::Qwen38_27b);
        assert_eq!(s.qwen.context, 262144);
        assert_eq!(s.qwen.mtp, 3);
        assert_eq!(s.qwen.thinking, "xhigh");
        assert!(s.qwen.fast_start);
        assert!(s.qwen.text_only);
        assert!(!s.qwen.no_async_scheduling);
        assert_eq!(s.keepalive_min, 480);
        s.validate().unwrap();
    }

    #[test]
    fn qwen_args_match_existing_profile() {
        let args = Settings::default().serve_args();
        let joined = args.join(" ");
        assert!(joined.contains("--model qwen38-27b"));
        assert!(joined.contains("--max-model-len 262144"));
        assert!(joined.contains("--mtp 3"));
        assert!(joined.contains("--reasoning-effort xhigh"));
        assert!(joined.contains("--fast-start"));
        assert!(joined.contains("--text-only"));
        assert!(!joined.contains("--no-tools"));
    }

    #[test]
    fn glm_args_use_glm_profile_only() {
        let mut s = Settings::default();
        s.model = ModelId::Glm53Flash;
        let joined = s.serve_args().join(" ");
        assert!(joined.contains("--model glm53-flash"));
        assert!(joined.contains("--max-len 262144"));
        assert!(joined.contains("--streams 3"));
        assert!(joined.contains("--reasoning-effort low"));
        assert!(!joined.contains("--mtp"));
        assert!(!joined.contains("--fast-start"));
    }

    #[test]
    fn legacy_settings_are_migrated_to_qwen_profile() {
        let s = Settings::from_json(
            r#"{"projectRoot":"C:\\repo","context":131072,"mtp":1,"thinking":"medium","fastStart":false,"textOnly":false,"keepaliveMin":120}"#,
        )
        .unwrap();
        assert_eq!(s.model, ModelId::Qwen38_27b);
        assert_eq!(s.project_root.as_deref(), Some("C:\\repo"));
        assert_eq!(s.qwen.context, 131072);
        assert_eq!(s.qwen.mtp, 1);
        assert_eq!(s.qwen.thinking, "medium");
        assert!(!s.qwen.fast_start);
        assert!(!s.qwen.text_only);
        assert_eq!(s.keepalive_min, 120);
    }

    #[test]
    fn glm_saved_legacy_streams_migrate_to_three() {
        let s = Settings::from_json(r#"{"model":"glm53-flash","glm":{"streams":4}}"#).unwrap();
        assert_eq!(s.glm.streams, 3);
        s.validate().unwrap();
    }

    #[test]
    fn glm_streams_above_three_are_rejected() {
        let mut s = Settings::default();
        s.model = ModelId::Glm53Flash;
        s.glm.streams = 4;
        assert!(s.validate().is_err());
        s.glm.streams = 3;
        s.validate().unwrap();
    }

    #[test]
    fn model_specific_validation_is_enforced() {
        let mut q = Settings::default();
        q.qwen.mtp = 99;
        assert!(q.validate().is_err());

        let mut g = Settings::default();
        g.model = ModelId::Glm53Flash;
        g.glm.thinking = "medium".into();
        assert!(g.validate().is_err());
        g.glm.thinking = "high".into();
        g.glm.streams = 0;
        assert!(g.validate().is_err());
    }
}
