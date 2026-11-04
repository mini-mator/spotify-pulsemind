let currentDraftId = null;

async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function apiPost(path, body = {}) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

function renderInspector(profile, isLive = false, source = "reccobeats") {
  if (!profile) return;
  document.getElementById("np-status-tag").textContent = isLive
    ? "LIVE NOW PLAYING"
    : "INSPECTING TRACK PROFILE";
  document.getElementById("np-title").textContent = profile.title;
  document.getElementById("np-artist").textContent = `${profile.artist}${profile.album ? " • " + profile.album : ""}`;

  const audio = profile.audio || {};
  const interp = profile.interpretation || {};

  document.getElementById("np-bpm").textContent = Math.round(audio.tempo || 120);
  const srcBadge = document.getElementById("inspector-source-badge");
  const confPct = Math.round((audio.confidence || 0.9) * 100);
  srcBadge.textContent = `Audio: ${audio.source || source} (${confPct}% conf) • Lyrics: ${
    profile.has_lyrics_analyzed ? "LRCLIB Analyzed" : "Audio-Only"
  }`;

  const setBar = (idBar, idVal, val) => {
    const v = Number(val ?? 0.5);
    document.getElementById(idBar).style.width = `${Math.round(v * 100)}%`;
    document.getElementById(idVal).textContent = v.toFixed(2);
  };
  setBar("bar-energy", "val-energy", audio.energy);
  setBar("bar-dance", "val-dance", audio.danceability);
  setBar("bar-valence", "val-valence", audio.valence);

  document.getElementById("np-beat-label").textContent =
    profile.beat_label || interp.beat_archetype;
  document.getElementById("np-beat-desc").textContent =
    interp.beat_descriptor || "—";

  const macroLabel = profile.secondary_theme_label
    ? `${profile.primary_theme_label} • ${profile.secondary_theme_label}`
    : profile.primary_theme_label || interp.primary_theme;
  const headline = interp.specific_theme_headline || macroLabel;
  document.getElementById("np-theme-label").textContent = headline;
  document.getElementById("np-message").textContent = interp.music_message || "—";
  const motifText = interp.key_lyric_motif ? `Motif: "${interp.key_lyric_motif}" • ` : "";
  document.getElementById("np-arc").textContent = `${motifText}Arc: ${interp.emotional_arc || "—"}`;
  document.getElementById("np-perspective").textContent = `Macro DNA: ${macroLabel} (${profile.llm_provider_used || "llm"})`;

  const tagsEl = document.getElementById("np-tags");
  tagsEl.innerHTML = "";
  (interp.custom_tags || []).forEach((t) => {
    const span = document.createElement("span");
    span.className = "chip";
    span.textContent = `#${t}`;
    tagsEl.appendChild(span);
  });
}

async function loadVocabularies() {
  const data = await apiGet("/api/vocabularies");
  const beatSel = document.getElementById("rec-beat");
  const themeSel = document.getElementById("rec-theme");

  data.beat_archetypes.forEach((b) => {
    const opt = document.createElement("option");
    opt.value = b.id;
    opt.textContent = b.label;
    beatSel.appendChild(opt);
  });

  data.lyrical_themes.forEach((t) => {
    const opt = document.createElement("option");
    opt.value = t.id;
    opt.textContent = t.label;
    themeSel.appendChild(opt);
  });
}

async function refreshStatus() {
  const st = await apiGet("/api/status");
  const spPill = document.getElementById("pill-spotify");
  if (st.spotify_authenticated) {
    spPill.textContent = "Spotify PKCE: Connected Live";
    spPill.className = "pill pill-ok";
  } else if (st.desktop_session_active) {
    const isPlaying = st.now_playing && st.now_playing.is_playing;
    spPill.textContent = isPlaying
      ? "Active Spotify Desktop: Connected & Playing"
      : "Active Spotify Desktop: Connected (Paused)";
    spPill.className = "pill pill-ok";
  } else {
    spPill.textContent = "Spotify Desktop: Waiting for Active Playback...";
    spPill.className = "pill pill-warn";
  }

  const privPill = document.getElementById("pill-privacy");
  privPill.textContent =
    st.privacy_mode === "local_only"
      ? `Privacy: Local Lyrics Analysis (${st.llm_provider})`
      : `Privacy: Cloud LLM Lyrics Enabled (${st.llm_provider})`;

  document.getElementById("btn-toggle-tracker").textContent = st.tracker_paused
    ? "Resume Tracker"
    : "Pause Tracker";

  if (st.now_playing && st.now_playing.profile) {
    renderInspector(st.now_playing.profile, st.now_playing.is_live);
  }
}

async function refreshTasteDNA() {
  const dna = await apiGet("/api/taste-dna");
  document.getElementById("dna-bpm").textContent = Math.round(dna.avg_bpm || 120);
  document.getElementById("dna-plays").textContent = dna.total_plays || 0;
  document.getElementById("dna-repeat-rate").textContent = `${dna.repeat_rate || 0}%`;
  document.getElementById("dna-skip-rate").textContent = `${dna.skip_rate || 0}%`;
  document.getElementById("dna-night-share").textContent = `${dna.late_night_share || 0}%`;

  const renderDist = (containerId, items) => {
    const el = document.getElementById(containerId);
    el.innerHTML = "";
    items.slice(0, 5).forEach((item) => {
      const div = document.createElement("div");
      div.className = "dist-item";
      div.innerHTML = `
        <div class="dist-top">
          <span>${item.label}</span>
          <strong>${item.share}%</strong>
        </div>
        <div class="bar-bg">
          <div class="bar-fill" style="width:${Math.min(100, item.share)}%"></div>
        </div>
      `;
      el.appendChild(div);
    });
  };

  renderDist("dna-beats-list", dna.beat_distribution || []);
  renderDist("dna-themes-list", dna.theme_distribution || []);
}

async function refreshHistory() {
  const data = await apiGet("/api/history?limit=25");
  const tbody = document.getElementById("history-tbody");
  tbody.innerHTML = "";

  (data.events || []).forEach((ev) => {
    const tr = document.createElement("tr");
    const pct = Math.round((ev.completion_ratio || 0) * 100);
    let behaviorHtml = `<span>Completed (${pct}%)</span>`;
    if (ev.was_skipped) {
      behaviorHtml = `<span class="status-skip">Skipped Early (${pct}%)</span>`;
    } else if (ev.repeat_count > 0) {
      behaviorHtml = `<span class="status-repeat">Repeated ×${ev.repeat_count} Loops</span>`;
    }

    const bpm = Math.round(ev.audio?.tempo || 120);
    const src = ev.audio?.source || "reccobeats";

    tr.innerHTML = `
      <td>
        <strong>${ev.title}</strong><br/>
        <span class="muted small">${ev.artist}</span>
      </td>
      <td>
        <strong>${ev.beat_label}</strong><br/>
        <span class="muted small">${(ev.interpretation?.beat_descriptor || "").slice(0, 68)}...</span>
      </td>
      <td>
        <strong>${ev.theme_label}</strong><br/>
        <span class="muted small">${(ev.interpretation?.music_message || "").slice(0, 75)}...</span>
      </td>
      <td>
        <strong>${bpm} BPM</strong><br/>
        <span class="muted small">${src}</span>
      </td>
      <td>${behaviorHtml}</td>
      <td>
        <div style="display:flex; gap:5px; flex-wrap:wrap;">
          <button class="btn btn-secondary btn-sm" onclick="simulateEvent('${ev.track_id}', 'repeat_loop')">+Repeat Loop</button>
          <button class="btn btn-ghost btn-sm" onclick="simulateEvent('${ev.track_id}', 'skip')">Simulate Skip</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function simulateEvent(trackId, action) {
  await apiPost("/api/simulate-event", { track_id: trackId, action });
  await Promise.all([refreshTasteDNA(), refreshHistory(), refreshStatus()]);
}

async function generatePlaylistPreview() {
  const btn = document.getElementById("btn-generate-preview");
  btn.textContent = "Scoring Candidates...";
  btn.disabled = true;
  try {
    const bpmVal = document.getElementById("rec-bpm").value.trim();
    const payload = {
      prompt: document.getElementById("rec-prompt").value.trim(),
      beat_archetype: document.getElementById("rec-beat").value,
      lyrical_theme: document.getElementById("rec-theme").value,
      target_bpm: bpmVal ? Number(bpmVal) : null,
      playlist_size: Number(document.getElementById("rec-size").value || 6),
    };
    const res = await apiPost("/api/playlist/preview", payload);
    renderPlaylistDraft(res.draft);
  } catch (err) {
    alert("Error generating preview: " + err.message);
  } finally {
    btn.textContent = "Generate Playlist Preview";
    btn.disabled = false;
  }
}

function renderPlaylistDraft(draft) {
  currentDraftId = draft.draft_id;
  const box = document.getElementById("playlist-preview-container");
  box.classList.remove("hidden");

  document.getElementById("draft-title").textContent = draft.name;
  document.getElementById("draft-desc").textContent = draft.description;

  const exportLink = document.getElementById("link-exported-spotify");
  if (draft.exported_spotify_url) {
    exportLink.href = draft.exported_spotify_url;
    exportLink.classList.remove("hidden");
  } else {
    exportLink.classList.add("hidden");
  }

  const grid = document.getElementById("draft-tracks-grid");
  grid.innerHTML = "";
  (draft.tracks || []).forEach((t) => {
    const card = document.createElement("div");
    card.className = "rec-card";
    card.innerHTML = `
      <div class="rec-card-top">
        <div>
          <strong>${t.title}</strong>
          <div class="muted small">${t.artist} • ${Math.round(t.bpm)} BPM (${t.feature_source})</div>
        </div>
        <span class="match-pill">${t.match_percent}% DNA Match</span>
      </div>
      <div class="rec-why">${t.why_matched}</div>
      <p class="rec-msg"><strong>Theme:</strong> ${t.specific_theme_headline || t.theme_label}</p>
      <p class="rec-msg"><strong>Beat:</strong> ${t.beat_descriptor}</p>
      <p class="rec-msg"><strong>Message:</strong> ${t.music_message}</p>
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:4px;">
        <span class="muted small">Origin: ${t.candidate_origin} • Cosine: ${t.cosine_similarity}</span>
        <a href="${t.spotify_url}" target="_blank" class="btn btn-secondary btn-sm">Open Track ↗</a>
      </div>
    `;
    grid.appendChild(card);
  });
}

async function confirmExportPlaylist() {
  if (!currentDraftId) return;
  const btn = document.getElementById("btn-confirm-export");
  btn.textContent = "Creating Private Spotify Playlist...";
  btn.disabled = true;
  try {
    const res = await apiPost(`/api/playlist/export/${currentDraftId}`);
    const exportLink = document.getElementById("link-exported-spotify");
    exportLink.href = res.spotify_url;
    exportLink.classList.remove("hidden");
    alert("Playlist exported to your Spotify account as a Private Playlist!");
  } catch (err) {
    alert(err.message);
  } finally {
    btn.textContent = "Step 2: Confirm & Save Private Playlist to Spotify";
    btn.disabled = false;
  }
}

async function openSettingsModal() {
  const data = await apiGet("/api/settings");
  const s = data.settings;
  const sec = data.secrets_status;

  document.getElementById("set-llm-provider").value = s.llm_provider || "ollama";
  document.getElementById("set-llm-model").value = s.llm_model || "llama3.2";
  document.getElementById("set-winmedia").checked = Boolean(s.enable_windows_media_fallback);
  document.getElementById("set-send-lyrics-cloud").checked = Boolean(s.send_lyrics_to_cloud_llm);

  document.getElementById("lbl-spotify-masked").textContent = sec.has_spotify_client_id
    ? `Saved in OS Keyring: ${sec.spotify_client_id_masked}`
    : "No Spotify Client ID saved yet.";
  document.getElementById("lbl-llm-masked").textContent = sec.has_llm_api_key
    ? `Saved in OS Keyring: ${sec.llm_api_key_masked}`
    : "No Cloud LLM key saved yet.";

  const w = s.weights || {};
  document.getElementById("w-halflife").value = w.half_life_days ?? 14;
  document.getElementById("w-skip-ms").value = w.skip_min_ms ?? 30000;
  document.getElementById("w-skip-ratio").value = w.skip_min_ratio ?? 0.5;
  document.getElementById("w-skip-penalty").value = w.skip_penalty_weight ?? 0.15;
  document.getElementById("w-repeat-bonus").value = w.repeat_bonus_per_loop ?? 0.45;
  document.getElementById("w-night-boost").value = w.late_night_boost ?? 1.35;

  document.getElementById("settings-modal").classList.remove("hidden");
}

async function saveSettings() {
  const current = (await apiGet("/api/settings")).settings;
  const weights = {
    ...current.weights,
    half_life_days: Number(document.getElementById("w-halflife").value || 14),
    skip_min_ms: Number(document.getElementById("w-skip-ms").value || 30000),
    skip_min_ratio: Number(document.getElementById("w-skip-ratio").value || 0.5),
    skip_penalty_weight: Number(document.getElementById("w-skip-penalty").value || 0.15),
    repeat_bonus_per_loop: Number(document.getElementById("w-repeat-bonus").value || 0.45),
    late_night_boost: Number(document.getElementById("w-night-boost").value || 1.35),
  };

  const payload = {
    llm_provider: document.getElementById("set-llm-provider").value,
    llm_model: document.getElementById("set-llm-model").value.trim(),
    ollama_base_url: current.ollama_base_url || "http://127.0.0.1:11434",
    send_lyrics_to_cloud_llm: document.getElementById("set-send-lyrics-cloud").checked,
    enable_windows_media_fallback: document.getElementById("set-winmedia").checked,
    demo_mode: false,
    weights,
    spotify_client_id: document.getElementById("set-spotify-id").value.trim() || null,
    llm_api_key: document.getElementById("set-llm-key").value.trim() || null,
    lastfm_api_key: document.getElementById("set-lastfm-key").value.trim() || null,
  };

  await apiPost("/api/settings", payload);
  document.getElementById("settings-save-msg").textContent = "Saved securely to OS Keyring & SQLite!";
  await Promise.all([refreshStatus(), refreshTasteDNA(), refreshHistory()]);
  setTimeout(() => {
    document.getElementById("settings-modal").classList.add("hidden");
    document.getElementById("settings-save-msg").textContent = "";
  }, 600);
}

window.addEventListener("DOMContentLoaded", async () => {
  await loadVocabularies();
  await Promise.all([refreshStatus(), refreshTasteDNA(), refreshHistory()]);
  await generatePlaylistPreview();

  // Auto-refresh live Spotify playback, Taste DNA, and History every 5 seconds
  setInterval(async () => {
    try {
      await Promise.all([refreshStatus(), refreshTasteDNA(), refreshHistory()]);
    } catch (_) {}
  }, 5000);

  document.getElementById("btn-generate-preview").addEventListener("click", generatePlaylistPreview);
  document.getElementById("btn-confirm-export").addEventListener("click", confirmExportPlaylist);

  document.getElementById("btn-toggle-tracker").addEventListener("click", async () => {
    await apiPost("/api/tracker/toggle");
    await refreshStatus();
  });

  document.getElementById("btn-analyze-now").addEventListener("click", async () => {
    const title = document.getElementById("inp-analyze-title").value.trim();
    const artist = document.getElementById("inp-analyze-artist").value.trim();
    const track_id = document.getElementById("inp-analyze-id").value.trim();
    if (!title || !artist) {
      alert("Please enter both a Song Title and Artist.");
      return;
    }
    const btn = document.getElementById("btn-analyze-now");
    btn.textContent = "Profiling...";
    btn.disabled = true;
    try {
      const res = await apiPost("/api/analyze-track", { track_id, title, artist });
      renderInspector(res.profile, false);
    } catch (err) {
      alert("Error analyzing track: " + err.message);
    } finally {
      btn.textContent = "Profile Track";
      btn.disabled = false;
    }
  });

  document.getElementById("btn-open-settings").addEventListener("click", openSettingsModal);
  document.getElementById("btn-close-settings").addEventListener("click", () => {
    document.getElementById("settings-modal").classList.add("hidden");
  });
  document.getElementById("btn-save-settings").addEventListener("click", saveSettings);

  document.getElementById("btn-connect-spotify").addEventListener("click", async () => {
    const clientInput = document.getElementById("set-spotify-id").value.trim();
    if (clientInput) {
      await saveSettings();
    }
    try {
      const res = await apiGet("/api/spotify/auth-url");
      window.location.href = res.authorize_url;
    } catch (err) {
      alert(err.message);
    }
  });
});
