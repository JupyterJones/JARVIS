use serde::{Deserialize, Serialize};
use std::process::Command;
use std::time::Duration;
use sysinfo::System;

const OLLAMA_HOST: &str = "http://127.0.0.1:11434";
const KOBOLD_HOST: &str = "http://127.0.0.1:5001";
const GENEROUS_TIMEOUT_SECS: u64 = 900; // 15 minutes - NEVER short timeout!

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct TelemetryData {
    pub cpu_usage: f32,
    pub ram_percent: f32,
    pub ram_used_gb: f32,
    pub ram_total_gb: f32,
    pub root_disk_percent: f32,
    pub root_disk_free_gb: f32,
    pub ollama_ssd_mounted: bool,
    pub uptime_hours: f32,
    pub clock: String,
    pub date: String,
}

#[tauri::command]
fn get_telemetry() -> Result<TelemetryData, String> {
    let mut sys = System::new_all();
    sys.refresh_all();
    std::thread::sleep(Duration::from_millis(150));
    sys.refresh_cpu();

    let cpu = sys.global_cpu_info().cpu_usage();
    let total_ram = sys.total_memory() as f32 / (1024.0 * 1024.0 * 1024.0);
    let used_ram = sys.used_memory() as f32 / (1024.0 * 1024.0 * 1024.0);
    let ram_percent = if total_ram > 0.0 { (used_ram / total_ram) * 100.0 } else { 0.0 };

    let disks = sysinfo::Disks::new_with_refreshed_list();
    let mut root_used_pct = 0.0;
    let mut root_free_gb = 0.0;
    let mut ollama_mounted = false;

    for disk in disks.list() {
        let mount = disk.mount_point().to_string_lossy();
        if mount == "/" {
            let total = disk.total_space() as f32;
            let available = disk.available_space() as f32;
            root_free_gb = available / (1024.0 * 1024.0 * 1024.0);
            if total > 0.0 {
                root_used_pct = ((total - available) / total) * 100.0;
            }
        } else if mount.contains("OLLAMA_SSD") {
            ollama_mounted = true;
        }
    }

    let uptime = System::uptime() as f32 / 3600.0;
    let now = chrono::Local::now();

    Ok(TelemetryData {
        cpu_usage: cpu,
        ram_percent,
        ram_used_gb: (used_ram * 10.0).round() / 10.0,
        ram_total_gb: (total_ram * 10.0).round() / 10.0,
        root_disk_percent: (root_used_pct * 10.0).round() / 10.0,
        root_disk_free_gb: (root_free_gb * 10.0).round() / 10.0,
        ollama_ssd_mounted: ollama_mounted,
        uptime_hours: (uptime * 10.0).round() / 10.0,
        clock: now.format("%H:%M:%S").to_string(),
        date: now.format("%A, %d %B %Y").to_string().to_uppercase(),
    })
}

#[tauri::command]
fn get_models() -> Result<Vec<String>, String> {
    let mut models = Vec::new();
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(4))
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

    let system_prompt = "You are Esperanza, Jack's loyal, brilliant, warm, and fiercely capable Jarvis-like AI co-pilot. You run natively on his Linux workstation. Answer directly, concisely, and with charm. Always treat Jack as your visionary creator and partner.";

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
            .map_err(|e| format!("Kobold Connection Error: {}", e))?;

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
            .map_err(|e| format!("Ollama Connection Error: {}", e))?;

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

#[tauri::command]
fn speak_text(text: String, voice: String) -> Result<String, String> {
    let clean = text.replace('"', "").replace('\'', "").replace('*', "").replace('#', "");
    let sentences: Vec<&str> = clean.split('.').filter(|s| !s.trim().is_empty()).collect();
    let spoken = if sentences.len() > 2 {
        format!("{}. {}.", sentences[0].trim(), sentences[1].trim())
    } else {
        clean
    };

    std::thread::spawn(move || {
        let script = format!(
            "from kokoro_tts import Kokoro; import sounddevice as sd; k = Kokoro('/home/jack/Desktop/Kokoro-TTS-Pause/kokoro-v1.0.onnx', '/home/jack/Desktop/Kokoro-TTS-Pause/voices-v1.0.bin'); s, r = k.create('''{}''', voice='{}', speed=1.05); sd.play(s, r); sd.wait()",
            spoken, voice
        );
        let _ = Command::new("python3").args(["-c", &script]).output();
    });

    Ok("Vocalization queued".to_string())
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
            let script = r#"
import datetime
from PIL import ImageGrab
from pathlib import Path
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
p = Path("/home/jack/Desktop/JARVIS/screenshots")
p.mkdir(exist_ok=True)
dest = p / f"screenshot_{ts}.png"
ImageGrab.grab().save(str(dest))
print(dest)
"#;
            let out = Command::new("python3").args(["-c", script]).output().map_err(|e| e.to_string())?;
            let dest = String::from_utf8_lossy(&out.stdout).trim().to_string();
            Ok(format!("Screenshot saved to: {}", dest))
        }
        "weather" => {
            let out = Command::new("curl").args(["-s", "https://wttr.in/?format=%C+%t+(feels+like+%f),+humidity+%h,+wind+%w"]).output().map_err(|e| e.to_string())?;
            Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
        }
        "start_kobold" => {
            let _ = Command::new("bash").arg("/home/jack/Desktop/JARVIS/launch_kobold_vulkan.sh").spawn();
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
            execute_action
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
