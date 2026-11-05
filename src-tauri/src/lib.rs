use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;
use sysinfo::System;

const OLLAMA_HOST: &str = "http://127.0.0.1:11434";
const KOBOLD_HOST: &str = "http://127.0.0.1:5001";
const GENEROUS_TIMEOUT_SECS: u64 = 900; // 15 minutes - NEVER short timeout!

/// Resolves the host directory where the application/AppImage is running.
/// In an AppImage, `$APPIMAGE` points to the actual `.AppImage` binary on the host drive.
/// This ensures `./notes/` and `./screenshots/` live alongside the AppImage, fully persistent.
fn get_app_dir() -> PathBuf {
    if let Ok(appimage_path) = std::env::var("APPIMAGE") {
        if let Some(parent) = Path::new(&appimage_path).parent() {
            return parent.to_path_buf();
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct NoteItem {
    pub id: String,
    pub timestamp: String,
    pub title: String,
    pub content: String,
    pub filename: String,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct TelemetryData {
    pub cpu_usage: f32,
    pub ram_percent: f32,
    pub ram_used_gb: f32,
    pub ram_total_gb: f32,
    pub root_disk_percent: f32,
    pub root_disk_free_gb: f32,
    pub secondary_storage_mounted: bool,
    pub uptime_hours: f32,
    pub clock: String,
    pub date: String,
    pub notes_count: usize,
}

#[tauri::command]
fn get_telemetry() -> Result<TelemetryData, String> {
    let mut sys = System::new_all();
    sys.refresh_all();
    std::thread::sleep(Duration::from_millis(120));
    sys.refresh_cpu();

    let cpu = sys.global_cpu_info().cpu_usage();
    let total_ram = sys.total_memory() as f32 / (1024.0 * 1024.0 * 1024.0);
    let used_ram = sys.used_memory() as f32 / (1024.0 * 1024.0 * 1024.0);
    let ram_percent = if total_ram > 0.0 { (used_ram / total_ram) * 100.0 } else { 0.0 };

    let disks = sysinfo::Disks::new_with_refreshed_list();
    let mut root_used_pct = 0.0;
    let mut root_free_gb = 0.0;
    let mut secondary_mounted = false;

    for disk in disks.list() {
        let mount = disk.mount_point().to_string_lossy();
        if mount == "/" {
            let total = disk.total_space() as f32;
            let available = disk.available_space() as f32;
            root_free_gb = available / (1024.0 * 1024.0 * 1024.0);
            if total > 0.0 {
                root_used_pct = ((total - available) / total) * 100.0;
            }
        } else if mount.contains("OLLAMA_SSD") || mount.starts_with("/media") || mount.starts_with("/mnt") {
            secondary_mounted = true;
        }
    }

    let uptime = System::uptime() as f32 / 3600.0;
    let now = chrono::Local::now();

    // Count notes in self-contained notes directory
    let notes_dir = get_app_dir().join("notes");
    let notes_count = if notes_dir.exists() {
        fs::read_dir(&notes_dir).map(|entries| {
            entries.flatten().filter(|e| e.path().extension().and_then(|x| x.to_str()) == Some("md")).count()
        }).unwrap_or(0)
    } else {
        0
    };

    Ok(TelemetryData {
        cpu_usage: cpu,
        ram_percent,
        ram_used_gb: (used_ram * 10.0).round() / 10.0,
        ram_total_gb: (total_ram * 10.0).round() / 10.0,
        root_disk_percent: (root_used_pct * 10.0).round() / 10.0,
        root_disk_free_gb: (root_free_gb * 10.0).round() / 10.0,
        secondary_storage_mounted: secondary_mounted,
        uptime_hours: (uptime * 10.0).round() / 10.0,
        clock: now.format("%H:%M:%S").to_string(),
        date: now.format("%A, %d %B %Y").to_string().to_uppercase(),
        notes_count,
    })
}

#[tauri::command]
fn get_models() -> Result<Vec<String>, String> {
    let mut models = Vec::new();
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(3))
        .build()
        .unwrap_or_default();

    // Probe KoboldCpp
    if let Ok(res) = client.get(format!("{}/api/v1/model", KOBOLD_HOST)).send() {
        if res.status().is_success() {
            if let Ok(json) = res.json::<serde_json::Value>() {
                let mname = json.get("result").and_then(|v| v.as_str()).unwrap_or("Llama-GGUF");
                models.push(format!("⚡ Kobold: {}", mname));
            }
        }
    }

    // Probe Ollama
    if let Ok(res) = client.get(format!("{}/api/tags", OLLAMA_HOST)).send() {
        if res.status().is_success() {
            if let Ok(json) = res.json::<serde_json::Value>() {
                if let Some(list) = json.get("models").and_then(|v| v.as_array()) {
                    for item in list {
                        if let Some(name) = item.get("name").and_then(|v| v.as_str()) {
                            models.push(name.to_string());
                        }
                    }
                }
            }
        }
    }

    if models.is_empty() {
        models.push("llama3.2:3b".to_string());
    }

    Ok(models)
}

#[tauri::command]
fn query_llm(model: String, prompt: String, history: Vec<ChatMessage>) -> Result<String, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(GENEROUS_TIMEOUT_SECS))
        .build()
        .map_err(|e| e.to_string())?;

    let system_prompt = "You are Esperanza, Jack's loyal, brilliant, warm, and fiercely capable Jarvis-like AI co-pilot. You run natively on Linux workstations. Answer directly, concisely, and with charm. Always treat the user as your visionary co-pilot and creator.";

    if model.contains("Kobold") || model.starts_with("⚡") {
        let mut messages = vec![serde_json::json!({
            "role": "system",
            "content": system_prompt
        })];

        for h in history.iter().rev().take(8).rev() {
            messages.push(serde_json::json!({
                "role": h.role,
                "content": h.content
            }));
        }

        messages.push(serde_json::json!({
            "role": "user",
            "content": prompt
        }));

        let payload = serde_json::json!({
            "messages": messages,
            "max_tokens": 512,
            "temperature": 0.72
        });

        let res = client.post(format!("{}/v1/chat/completions", KOBOLD_HOST))
            .json(&payload)
            .send()
            .map_err(|e| format!("Kobold Connection Error (http://127.0.0.1:5001): {}", e))?;

        if !res.status().is_success() {
            return Err(format!("Kobold API returned status: {}", res.status()));
        }

        let json: serde_json::Value = res.json().map_err(|e| e.to_string())?;
        let reply = json["choices"][0]["message"]["content"]
            .as_str()
            .unwrap_or("No response content")
            .to_string();

        Ok(reply)
    } else {
        // Ollama API - strictly capped to 4 CPU threads!
        let mut messages = vec![serde_json::json!({
            "role": "system",
            "content": system_prompt
        })];

        for h in history.iter().rev().take(8).rev() {
            messages.push(serde_json::json!({
                "role": h.role,
                "content": h.content
            }));
        }

        messages.push(serde_json::json!({
            "role": "user",
            "content": prompt
        }));

        let payload = serde_json::json!({
            "model": model,
            "messages": messages,
            "stream": false,
            "options": {
                "num_thread": 4, // Strictly capped to 4 threads!
                "temperature": 0.72,
                "num_ctx": 4096
            }
        });

        let res = client.post(format!("{}/api/chat", OLLAMA_HOST))
            .json(&payload)
            .send()
            .map_err(|e| format!("Ollama Connection Error (http://127.0.0.1:11434): {}", e))?;

        if !res.status().is_success() {
            return Err(format!("Ollama API returned status: {}", res.status()));
        }

        let json: serde_json::Value = res.json().map_err(|e| e.to_string())?;
        let reply = json["message"]["content"]
            .as_str()
            .unwrap_or("No response content")
            .to_string();

        Ok(reply)
    }
}

/// Vocalizes text using local Kokoro ONNX if available, otherwise returns fallback error so the UI uses Web Speech API.
#[tauri::command]
fn speak_text(text: String, voice: String) -> Result<String, String> {
    let clean = text.replace('"', "").replace('\'', "").replace('*', "").replace('#', "");
    let sentences: Vec<&str> = clean.split('.').filter(|s| !s.trim().is_empty()).collect();
    let spoken = if sentences.len() > 2 {
        format!("{}. {}.", sentences[0].trim(), sentences[1].trim())
    } else {
        clean
    };

    let app_dir = get_app_dir();
    let local_model = app_dir.join("kokoro-v1.0.onnx");
    let local_voices = app_dir.join("voices-v1.0.bin");
    let jack_model = Path::new("/home/jack/Desktop/Kokoro-TTS-Pause/kokoro-v1.0.onnx");
    let jack_voices = Path::new("/home/jack/Desktop/Kokoro-TTS-Pause/voices-v1.0.bin");

    let (model_path, voices_path) = if local_model.exists() && local_voices.exists() {
        (local_model.to_string_lossy().to_string(), local_voices.to_string_lossy().to_string())
    } else if jack_model.exists() && jack_voices.exists() {
        (jack_model.to_string_lossy().to_string(), jack_voices.to_string_lossy().to_string())
    } else {
        // Return fallback indicator so UI runs Web Speech API
        return Err("WEB_SPEECH_FALLBACK".to_string());
    };

    std::thread::spawn(move || {
        let script = format!(
            "from kokoro_tts import Kokoro; import sounddevice as sd; k = Kokoro('{}', '{}'); s, r = k.create('''{}''', voice='{}', speed=1.05); sd.play(s, r); sd.wait()",
            model_path, voices_path, spoken, voice
        );
        let _ = Command::new("python3").args(["-c", &script]).output();
    });

    Ok("Vocalization queued via Kokoro ONNX".to_string())
}

#[tauri::command]
fn trigger_mic() -> Result<String, String> {
    let script = r#"
import speech_recognition as sr
r = sr.Recognizer()
with sr.Microphone() as source:
    r.adjust_for_ambient_noise(source, duration=0.6)
    audio = r.listen(source, timeout=8, phrase_time_limit=12)
    print(r.recognize_google(audio))
"#;

    let out = Command::new("python3")
        .args(["-c", script])
        .output()
        .map_err(|e| e.to_string())?;

    if out.status.success() {
        let text = String::from_utf8_lossy(&out.stdout).trim().to_string();
        Ok(text)
    } else {
        Err(String::from_utf8_lossy(&out.stderr).to_string())
    }
}

// ----------------------------------------------------------------------------
// PERSISTENT SELF-CONTAINED NOTES SUBSYSTEM
// ----------------------------------------------------------------------------

#[tauri::command]
fn save_note(title: String, content: String) -> Result<NoteItem, String> {
    let app_dir = get_app_dir();
    let notes_dir = app_dir.join("notes");
    fs::create_dir_all(&notes_dir).map_err(|e| format!("Failed to create notes directory: {}", e))?;

    let now = chrono::Local::now();
    let ts_file = now.format("%Y%m%d_%H%M%S").to_string();
    let ts_display = now.format("%Y-%m-%d %H:%M:%S").to_string();

    let clean_title = title.trim();
    let effective_title = if clean_title.is_empty() {
        "Untitled Note"
    } else {
        clean_title
    };

    let sanitized_slug: String = effective_title
        .chars()
        .map(|c| if c.is_alphanumeric() || c == '-' || c == '_' { c } else { '_' })
        .take(24)
        .collect();

    let fname = format!("note_{}_{}.md", ts_file, sanitized_slug);
    let filepath = notes_dir.join(&fname);

    let md_content = format!(
        "# {}\n*Created: {}*\n\n{}\n",
        effective_title, ts_display, content.trim()
    );

    fs::write(&filepath, md_content).map_err(|e| format!("Failed to write note: {}", e))?;

    Ok(NoteItem {
        id: ts_file,
        timestamp: ts_display,
        title: effective_title.to_string(),
        content: content.trim().to_string(),
        filename: fname,
    })
}

#[tauri::command]
fn list_notes() -> Result<Vec<NoteItem>, String> {
    let app_dir = get_app_dir();
    let notes_dir = app_dir.join("notes");
    if !notes_dir.exists() {
        let _ = fs::create_dir_all(&notes_dir);
        return Ok(Vec::new());
    }

    let mut notes = Vec::new();
    if let Ok(entries) = fs::read_dir(&notes_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) == Some("md") {
                if let Ok(raw) = fs::read_to_string(&path) {
                    let fname = path.file_name().unwrap().to_string_lossy().to_string();
                    let lines: Vec<&str> = raw.lines().collect();
                    let title = lines.first()
                        .map(|s| s.trim_start_matches('#').trim().to_string())
                        .unwrap_or_else(|| fname.clone());

                    let created = lines.iter()
                        .find(|l| l.starts_with("*Created:"))
                        .map(|l| l.trim_matches('*').replace("Created:", "").trim().to_string())
                        .unwrap_or_else(|| "".to_string());

                    let body = lines.iter()
                        .skip_while(|l| l.starts_with('#') || l.starts_with("*Created:") || l.is_empty())
                        .cloned()
                        .collect::<Vec<&str>>()
                        .join("\n");

                    notes.push(NoteItem {
                        id: fname.clone(),
                        timestamp: created,
                        title,
                        content: body,
                        filename: fname,
                    });
                }
            }
        }
    }

    notes.sort_by(|a, b| b.filename.cmp(&a.filename));
    Ok(notes)
}

#[tauri::command]
fn delete_note(filename: String) -> Result<String, String> {
    let app_dir = get_app_dir();
    let filepath = app_dir.join("notes").join(&filename);
    if filepath.exists() {
        fs::remove_file(&filepath).map_err(|e| format!("Failed to delete note: {}", e))?;
        Ok(format!("Deleted note: {}", filename))
    } else {
        Err("Note file not found".to_string())
    }
}

#[tauri::command]
fn execute_action(action: String) -> Result<String, String> {
    match action.as_str() {
        "volume_up" => {
            let _ = Command::new("pactl").args(["set-sink-volume", "@DEFAULT_SINK@", "+10%"]).output();
            Ok("Volume increased (+10%)".to_string())
        }
        "volume_down" => {
            let _ = Command::new("pactl").args(["set-sink-volume", "@DEFAULT_SINK@", "-10%"]).output();
            Ok("Volume decreased (-10%)".to_string())
        }
        "volume_mute" => {
            let _ = Command::new("pactl").args(["set-sink-mute", "@DEFAULT_SINK@", "toggle"]).output();
            Ok("Audio mute toggled".to_string())
        }
        "screenshot" => {
            let app_dir = get_app_dir();
            let shot_dir = app_dir.join("screenshots");
            let _ = fs::create_dir_all(&shot_dir);
            let now = chrono::Local::now().format("%Y%m%d_%H%M%S").to_string();
            let fname = format!("screenshot_{}.png", now);
            let file_path = shot_dir.join(&fname);

            let script = format!(
                "from PIL import ImageGrab; ImageGrab.grab().save(r'{}')",
                file_path.display()
            );
            let out = Command::new("python3").args(["-c", &script]).output();

            if let Ok(o) = out {
                if o.status.success() {
                    return Ok(format!("Screenshot saved to: ./screenshots/{}", fname));
                }
            }

            // Fallback: scrot
            let scrot = Command::new("scrot").arg(file_path.to_str().unwrap()).output();
            if scrot.map(|s| s.status.success()).unwrap_or(false) {
                Ok(format!("Screenshot saved to: ./screenshots/{}", fname))
            } else {
                Err("Screenshot capture failed. Ensure python3-pil or scrot is installed.".to_string())
            }
        }
        "weather" => {
            let out = Command::new("curl").args(["-s", "https://wttr.in/?format=%C+%t+(feels+like+%f),+humidity+%h,+wind+%w"]).output().map_err(|e| e.to_string())?;
            Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
        }
        "start_kobold" => {
            let app_dir = get_app_dir();
            let script = app_dir.join("launch_kobold_vulkan.sh");
            if script.exists() {
                let _ = Command::new("bash").arg(script).spawn();
            } else {
                let _ = Command::new("bash").arg("/home/jack/Desktop/JARVIS/launch_kobold_vulkan.sh").spawn();
            }
            Ok("KoboldCpp Vulkan Engine initializing in background...".to_string())
        }
        other if other.starts_with("wikipedia:") => {
            let topic = other.trim_start_matches("wikipedia:").trim();
            let url = format!("https://en.wikipedia.org/api/rest_v1/page/summary/{}", topic);
            let client = reqwest::blocking::Client::builder().timeout(Duration::from_secs(6)).build().map_err(|e| e.to_string())?;
            let res = client.get(&url).header("User-Agent", "JarvisStark/1.0").send().map_err(|e| e.to_string())?;
            if res.status().is_success() {
                let json: serde_json::Value = res.json().map_err(|e| e.to_string())?;
                let extract = json["extract"].as_str().unwrap_or("No extract found").to_string();
                Ok(extract)
            } else {
                Err(format!("Wikipedia query failed for: {}", topic))
            }
        }
        _ => Err(format!("Unknown action: {}", action))
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Enforce 4 threads across all OpenMP/BLAS libraries
    std::env::set_var("OMP_NUM_THREADS", "4");
    std::env::set_var("MKL_NUM_THREADS", "4");
    std::env::set_var("OPENBLAS_NUM_THREADS", "4");

    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            get_telemetry,
            get_models,
            query_llm,
            speak_text,
            trigger_mic,
            execute_action,
            save_note,
            list_notes,
            delete_note
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
