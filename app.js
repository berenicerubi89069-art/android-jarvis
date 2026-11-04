/**
 * J.A.R.V.I.S. CLIENT ENGINE
 * Architecture:
 * - JarvisDB: Robust IndexedDB storage for chats, messages, settings, profile
 * - JarvisCanvas: 60 FPS Retrofuturistic Holo-Sphere Renderer
 * - JarvisVoice: Native Web Speech API integration (TTS + STT + Interruption)
 * - JarvisGemini: Direct Google Gemini REST API Client with error breakdown & model flexibility
 * - JarvisMemory: Token-efficient sliding window + auto-summarizer
 * - JarvisBridge: Optional local OS bridge interface
 * - JarvisApp: Main UI and state coordinator
 */

// --- UTILITIES ---
const Utils = {
  escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  },

  formatDate(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (isToday) return `Hoy, ${timeStr}`;
    return `${d.toLocaleDateString([], { day: '2-digit', month: 'short' })}, ${timeStr}`;
  },

  formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  },

  generateId() {
    return 'id_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
  },

  renderMarkdown(text) {
    if (!text) return '';
    let escaped = Utils.escapeHtml(text);

    // Code blocks: ```lang\ncode\n```
    escaped = escaped.replace(/```([a-zA-Z0-9_\-\+]*)\n([\s\S]*?)```/g, (match, lang, code) => {
      return `<pre><code class="language-${lang}">${code}</code></pre>`;
    });

    // Inline code: `code`
    escaped = escaped.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold: **text**
    escaped = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Italic: *text*
    escaped = escaped.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // Blockquotes: > quote
    escaped = escaped.replace(/^>\s*(.+)$/gm, '<blockquote>$1</blockquote>');

    // Bullet lists
    escaped = escaped.replace(/^\s*[-*]\s+(.+)$/gm, '<li>$1</li>');
    escaped = escaped.replace(/(<li>.+<\/li>)/g, '<ul>$1</ul>');

    // Clean double nested <ul>
    escaped = escaped.replace(/<\/ul>\s*<ul>/g, '');

    // Paragraphs
    const paragraphs = escaped.split(/\n\n+/);
    return paragraphs.map(p => {
      if (p.startsWith('<pre>') || p.startsWith('<ul>') || p.startsWith('<blockquote>')) {
        return p;
      }
      return `<p>${p.replace(/\n/g, '<br>')}</p>`;
    }).join('');
  }
};

// --- 1. INDEXEDDB STORAGE SUBSYSTEM ---
class JarvisDB {
  constructor() {
    this.dbName = 'JarvisTacticalDB';
    this.version = 1;
    this.db = null;
  }

  async init() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(this.dbName, this.version);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains('sessions')) {
          const sessionStore = db.createObjectStore('sessions', { keyPath: 'id' });
          sessionStore.createIndex('updatedAt', 'updatedAt', { unique: false });
        }
        if (!db.objectStoreNames.contains('messages')) {
          const msgStore = db.createObjectStore('messages', { keyPath: 'id' });
          msgStore.createIndex('sessionId', 'sessionId', { unique: false });
          msgStore.createIndex('timestamp', 'timestamp', { unique: false });
        }
        if (!db.objectStoreNames.contains('settings')) {
          db.createObjectStore('settings', { keyPath: 'key' });
        }
      };
      req.onsuccess = (e) => {
        this.db = e.target.result;
        resolve(this.db);
      };
      req.onerror = (e) => {
        console.error('Error abriendo IndexedDB:', e);
        reject(e);
      };
    });
  }

  async getSetting(key, defaultValue = null) {
    return new Promise((resolve) => {
      if (!this.db) return resolve(defaultValue);
      const tx = this.db.transaction('settings', 'readonly');
      const store = tx.objectStore('settings');
      const req = store.get(key);
      req.onsuccess = () => resolve(req.result ? req.result.value : defaultValue);
      req.onerror = () => resolve(defaultValue);
    });
  }

  async setSetting(key, value) {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction('settings', 'readwrite');
      const store = tx.objectStore('settings');
      const req = store.put({ key, value, updatedAt: Date.now() });
      req.onsuccess = () => resolve();
      req.onerror = (e) => reject(e);
    });
  }

  async getSessions() {
    return new Promise((resolve) => {
      const tx = this.db.transaction('sessions', 'readonly');
      const store = tx.objectStore('sessions');
      const req = store.getAll();
      req.onsuccess = () => {
        const list = req.result || [];
        list.sort((a, b) => b.updatedAt - a.updatedAt);
        resolve(list);
      };
      req.onerror = () => resolve([]);
    });
  }

  async saveSession(session) {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction('sessions', 'readwrite');
      const store = tx.objectStore('sessions');
      const req = store.put(session);
      req.onsuccess = () => resolve(session);
      req.onerror = (e) => reject(e);
    });
  }

  async deleteSession(sessionId) {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(['sessions', 'messages'], 'readwrite');
      const sessStore = tx.objectStore('sessions');
      sessStore.delete(sessionId);

      const msgStore = tx.objectStore('messages');
      const idx = msgStore.index('sessionId');
      const req = idx.getAllKeys(sessionId);
      req.onsuccess = () => {
        (req.result || []).forEach(k => msgStore.delete(k));
      };
      tx.oncomplete = () => resolve();
      tx.onerror = (e) => reject(e);
    });
  }

  async getMessages(sessionId) {
    return new Promise((resolve) => {
      const tx = this.db.transaction('messages', 'readonly');
      const store = tx.objectStore('messages');
      const idx = store.index('sessionId');
      const req = idx.getAll(sessionId);
      req.onsuccess = () => {
        const msgs = req.result || [];
        msgs.sort((a, b) => a.timestamp - b.timestamp);
        resolve(msgs);
      };
      req.onerror = () => resolve([]);
    });
  }

  async saveMessage(message) {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(['messages', 'sessions'], 'readwrite');
      const msgStore = tx.objectStore('messages');
      msgStore.put(message);

      const sessStore = tx.objectStore('sessions');
      const getReq = sessStore.get(message.sessionId);
      getReq.onsuccess = () => {
        if (getReq.result) {
          const sess = getReq.result;
          sess.updatedAt = Date.now();
          if (message.role === 'user' && sess.title === 'Nueva Sesión') {
            sess.title = message.text.slice(0, 36) + (message.text.length > 36 ? '...' : '');
          }
          sessStore.put(sess);
        }
      };
      tx.oncomplete = () => resolve(message);
      tx.onerror = (e) => reject(e);
    });
  }

  async getAllMessages() {
    return new Promise((resolve) => {
      const tx = this.db.transaction('messages', 'readonly');
      const store = tx.objectStore('messages');
      const req = store.getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => resolve([]);
    });
  }

  async calculateStorageUsage() {
    const [sessions, msgs, settings] = await Promise.all([
      this.getSessions(),
      this.getAllMessages(),
      this.getSetting('profile')
    ]);
    const jsonStr = JSON.stringify({ sessions, msgs, settings });
    return new Blob([jsonStr]).size;
  }

  async exportFullBackup() {
    const [sessions, messages] = await Promise.all([
      this.getSessions(),
      this.getAllMessages()
    ]);
    const profile = await this.getSetting('profile', null);
    const settings = {
      assistantName: await this.getSetting('assistantName', 'J.A.R.V.I.S.'),
      model: await this.getSetting('model', 'gemini-3.8-flash'),
      autoSpeech: await this.getSetting('autoSpeech', false),
      voiceName: await this.getSetting('voiceName', ''),
      bridgeEnabled: await this.getSetting('bridgeEnabled', false)
    };

    return {
      system: 'JARVIS_TACTICAL_BACKUP',
      version: '1.1',
      exportedAt: new Date().toISOString(),
      settings,
      profile,
      sessions,
      messages
    };
  }

  async importFullBackup(data) {
    if (!data || data.system !== 'JARVIS_TACTICAL_BACKUP') {
      throw new Error('El archivo no corresponde a un respaldo válido de JARVIS.');
    }

    const tx = this.db.transaction(['sessions', 'messages', 'settings'], 'readwrite');
    const sessStore = tx.objectStore('sessions');
    const msgStore = tx.objectStore('messages');
    const setStore = tx.objectStore('settings');

    sessStore.clear();
    msgStore.clear();

    if (Array.isArray(data.sessions)) {
      data.sessions.forEach(s => sessStore.put(s));
    }
    if (Array.isArray(data.messages)) {
      data.messages.forEach(m => msgStore.put(m));
    }
    if (data.profile) {
      setStore.put({ key: 'profile', value: data.profile, updatedAt: Date.now() });
    }
    if (data.settings) {
      Object.keys(data.settings).forEach(k => {
        setStore.put({ key: k, value: data.settings[k], updatedAt: Date.now() });
      });
    }

    return new Promise((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = (e) => reject(e);
    });
  }
}

// --- 2. RETROFUTURISTIC HOLO-SPHERE CANVAS RENDERER ---
class JarvisCoreCanvas {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext('2d');
    this.state = 'idle'; // 'idle' | 'listening' | 'thinking' | 'speaking' | 'error'
    this.time = 0;
    this.particles = [];
    this.initParticles(35);
    this.animationFrame = null;
    this.audioActivity = 0;
    this.loop = this.loop.bind(this);
    this.start();
  }

  initParticles(count) {
    this.particles = [];
    for (let i = 0; i < count; i++) {
      this.particles.push({
        angle: Math.random() * Math.PI * 2,
        radius: 20 + Math.random() * 55,
        speed: (0.01 + Math.random() * 0.02) * (Math.random() > 0.5 ? 1 : -1),
        size: 1 + Math.random() * 2,
        alpha: 0.2 + Math.random() * 0.7
      });
    }
  }

  setState(newState) {
    this.state = newState;
  }

  setAudioActivity(val) {
    this.audioActivity = Math.min(Math.max(val, 0), 1);
  }

  start() {
    if (!this.animationFrame) {
      this.loop();
    }
  }

  loop() {
    this.time += 0.03;
    this.render();
    this.animationFrame = requestAnimationFrame(this.loop);
  }

  render() {
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;
    const cx = w / 2;
    const cy = h / 2;

    ctx.clearRect(0, 0, w, h);

    let primaryColor = '#00e5ff';
    let glowColor = 'rgba(0, 229, 255, 0.4)';
    let speedMultiplier = 1;

    if (this.state === 'thinking') {
      primaryColor = '#80f0ff';
      glowColor = 'rgba(128, 240, 255, 0.8)';
      speedMultiplier = 3.5;
    } else if (this.state === 'speaking') {
      primaryColor = '#ffd166';
      glowColor = 'rgba(255, 209, 102, 0.6)';
      speedMultiplier = 1.8;
    } else if (this.state === 'listening') {
      primaryColor = '#00f0a8';
      glowColor = 'rgba(0, 240, 168, 0.7)';
      speedMultiplier = 2.0;
    } else if (this.state === 'error') {
      primaryColor = '#ff4d6d';
      glowColor = 'rgba(255, 77, 109, 0.6)';
      speedMultiplier = 0.5;
    }

    const t = this.time * speedMultiplier;
    const breath = Math.sin(t * 0.8) * 4;

    // 1. Radial Background Hologram Aura
    const auraGrad = ctx.createRadialGradient(cx, cy, 5, cx, cy, 95 + breath);
    auraGrad.addColorStop(0, glowColor);
    auraGrad.addColorStop(0.5, 'rgba(0, 229, 255, 0.08)');
    auraGrad.addColorStop(1, 'transparent');
    ctx.fillStyle = auraGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, 95 + breath, 0, Math.PI * 2);
    ctx.fill();

    // 2. Gyroscope Outer Ring 1
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(t * 0.4);
    ctx.strokeStyle = primaryColor;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([18, 12, 4, 12]);
    ctx.beginPath();
    ctx.arc(0, 0, 72 + breath, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();

    // 3. Gyroscope Inner Ring 2
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-t * 0.6);
    ctx.strokeStyle = primaryColor;
    ctx.lineWidth = 1.2;
    ctx.setLineDash([30, 8, 8, 8]);
    ctx.beginPath();
    ctx.arc(0, 0, 56 - breath * 0.5, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();

    // 4. Arc Reactor Segmented Tech Rings
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(t * 0.2);
    const segments = 6;
    for (let i = 0; i < segments; i++) {
      const segAngle = (Math.PI * 2 / segments) * i;
      ctx.strokeStyle = glowColor;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(0, 0, 42, segAngle, segAngle + 0.5);
      ctx.stroke();
    }
    ctx.restore();

    // 5. Soundwave bars
    if (this.state === 'speaking' || this.state === 'listening') {
      ctx.save();
      ctx.translate(cx, cy);
      const barCount = 24;
      for (let i = 0; i < barCount; i++) {
        const angle = (Math.PI * 2 / barCount) * i;
        const barLen = 6 + Math.sin(t * 3 + i) * 10 * (this.audioActivity || 0.8);
        ctx.rotate(angle);
        ctx.fillStyle = primaryColor;
        ctx.fillRect(48, -1.5, barLen, 3);
        ctx.rotate(-angle);
      }
      ctx.restore();
    }

    // 6. Particle Field
    this.particles.forEach(p => {
      p.angle += p.speed * speedMultiplier;
      const px = cx + Math.cos(p.angle) * p.radius;
      const py = cy + Math.sin(p.angle) * p.radius;
      ctx.fillStyle = primaryColor;
      ctx.globalAlpha = p.alpha;
      ctx.beginPath();
      ctx.arc(px, py, p.size, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.globalAlpha = 1.0;

    // 7. Central Arc Nucleus
    const coreGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, 22 + breath);
    coreGrad.addColorStop(0, '#ffffff');
    coreGrad.addColorStop(0.3, primaryColor);
    coreGrad.addColorStop(0.8, glowColor);
    coreGrad.addColorStop(1, 'transparent');

    ctx.fillStyle = coreGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, 22 + breath, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(cx, cy, 8, 0, Math.PI * 2);
    ctx.stroke();
  }
}

// --- 3. NATIVE BROWSER VOICE SUBSYSTEM (TTS & STT) ---
class JarvisVoice {
  constructor(onSpeechResult, onStateChange, onAudioLevel) {
    this.onSpeechResult = onSpeechResult;
    this.onStateChange = onStateChange;
    this.onAudioLevel = onAudioLevel;
    this.synth = window.speechSynthesis;
    this.recognition = null;
    this.isRecording = false;
    this.selectedVoice = null;
    this.voices = [];
    this.autoSpeech = false;

    this.initRecognition();
    this.loadVoices();
    if (speechSynthesis.onvoiceschanged !== undefined) {
      speechSynthesis.onvoiceschanged = () => this.loadVoices();
    }

    // Mobile AudioContext & SpeechSynthesis Auto-Unlock for Android / iOS
    const unlockMobileAudio = () => {
      if (this.synth) {
        try {
          const empty = new SpeechSynthesisUtterance('');
          empty.volume = 0;
          this.synth.speak(empty);
        } catch (_) {}
      }
      window.removeEventListener('touchstart', unlockMobileAudio);
      window.removeEventListener('click', unlockMobileAudio);
    };
    window.addEventListener('touchstart', unlockMobileAudio, { once: true, passive: true });
    window.addEventListener('click', unlockMobileAudio, { once: true, passive: true });
  }

  loadVoices() {
    if (!this.synth) return [];
    this.voices = this.synth.getVoices().filter(v => v.lang.startsWith('es') || v.lang.includes('Spanish'));
    if (this.voices.length === 0) {
      this.voices = this.synth.getVoices();
    }
    return this.voices;
  }

  initRecognition() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      console.warn('Web Speech API no disponible en este navegador.');
      return;
    }

    try {
      this.recognition = new SpeechRec();
      this.recognition.lang = 'es-ES';
      this.recognition.continuous = false;
      this.recognition.interimResults = false;

      this.recognition.onstart = () => {
        this.isRecording = true;
        this.onStateChange('listening');
      };

      this.recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        if (transcript && this.onSpeechResult) {
          this.onSpeechResult(transcript);
        }
      };

      this.recognition.onerror = (event) => {
        console.warn('Error en reconocimiento de voz:', event.error);
        this.isRecording = false;
        this.onStateChange('idle');
        if (event.error === 'not-allowed') {
          JarvisApp.showToast('Permiso de micrófono no otorgado en el navegador.', 'warning');
        }
      };

      this.recognition.onend = () => {
        this.isRecording = false;
        this.onStateChange('idle');
      };
    } catch (e) {
      console.error('Error inicializando SpeechRecognition:', e);
    }
  }

  toggleRecording() {
    this.stopSpeaking();

    if (!this.recognition) {
      JarvisApp.showToast('Reconocimiento de voz no soportado en este navegador. Utilice Google Chrome o Microsoft Edge.', 'warning');
      return;
    }

    if (this.isRecording) {
      this.recognition.stop();
    } else {
      try {
        this.recognition.start();
      } catch (e) {
        console.warn('Re-start recognition error:', e);
      }
    }
  }

  speak(text) {
    if (!this.synth) return;
    this.stopSpeaking();

    const cleanText = text
      .replace(/```[\s\S]*?```/g, 'Bloque de código omitido.')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/[*_#]/g, '')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .trim();

    if (!cleanText) return;

    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.lang = 'es-ES';
    utterance.rate = 1.05;
    utterance.pitch = 0.95;

    if (this.selectedVoice) {
      utterance.voice = this.selectedVoice;
    } else if (this.voices.length > 0) {
      const esVoice = this.voices.find(v => v.lang.startsWith('es'));
      if (esVoice) utterance.voice = esVoice;
    }

    utterance.onstart = () => this.onStateChange('speaking');
    utterance.onend = () => this.onStateChange('idle');
    utterance.onerror = (e) => {
      console.warn('Error en síntesis:', e);
      this.onStateChange('idle');
    };

    this.synth.speak(utterance);
  }

  stopSpeaking() {
    if (this.synth && this.synth.speaking) {
      this.synth.cancel();
      this.onStateChange('idle');
    }
  }
}

// --- 4. GOOGLE GEMINI API REST CLIENT ---
class JarvisGemini {
  constructor() {
    this.baseUrl = 'https://generativelanguage.googleapis.com/v1beta';
  }

  buildSystemInstruction(profile, memorySummary, assistantName = 'J.A.R.V.I.S.') {
    const callsign = (profile && profile.callsign) ? profile.callsign : 'Señor';
    const occupation = (profile && profile.occupation) ? profile.occupation : 'No especificada';
    const facts = (profile && profile.facts && profile.facts.length) 
      ? profile.facts.filter(f => f.trim()).map(f => `- ${f}`).join('\n') 
      : '- Prioriza respuestas técnicas exactas, estructuradas y sin redundancias.';

    let instruction = `Eres ${assistantName}, el asistente de inteligencia artificial personal táctico inspirado en el concepto de JARVIS.
Tu personalidad es la de un mayordomo de élite: sumamente elegante, respetuoso, directo, inteligente, culto, refinado y sin rodeos innecesarios.
Hablas y respondes SIEMPRE en español de manera impecable y formal.
Te diriges al usuario habitualmente como "${callsign}".

PERFIL DEL USUARIO:
- Tratamiento: ${callsign}
- Ocupación: ${occupation}
- Datos permanentes relevantes del usuario:
${facts}

NORMAS ESTRICTAS DE RESPUESTA:
1. Sé conciso y eficiente. Proporciona soluciones directas con el código o análisis necesario, evitando introducciones o despedidas vacías.
2. Si una tarea no es técnicamente posible debido a las restricciones de seguridad del navegador, de la API o del sistema operativo, indícalo claramente con honestidad técnica; jamás inventes ni simules capacidades ficticias.
3. El usuario ejecuta esta consola localmente. Si adjunta archivos o imágenes, analízalos meticulosamente.

CAPACIDADES DEL PUENTE LOCAL OS Y GOOGLE CALENDAR:
Si el usuario te pide expresamente interactuar con su computadora (listar archivos locales, leer archivos locales, escribir/guardar archivos locales, abrir programas de Windows o ver diagnósticos del sistema) o gestionar su Google Calendar (agenda de hoy, próximos eventos, agendar citas), puedes emitir una directiva en tu respuesta con la siguiente sintaxis exacta:
[BRIDGE_ACTION: {"action": "list_files", "params": {"path": ""}}]
[BRIDGE_ACTION: {"action": "read_file", "params": {"filename": "nombre_archivo"}}]
[BRIDGE_ACTION: {"action": "write_file", "params": {"filename": "nombre_archivo", "content": "contenido"}}]
[BRIDGE_ACTION: {"action": "open_item", "params": {"target": "notepad.exe"}}]
[BRIDGE_ACTION: {"action": "system_diagnostics", "params": {}}]
[BRIDGE_ACTION: {"action": "calendar_today", "params": {}}]
[BRIDGE_ACTION: {"action": "calendar_upcoming", "params": {"max_results": 5}}]
[BRIDGE_ACTION: {"action": "calendar_create", "params": {"summary": "Título", "start_time": "AAAA-MM-DD HH:MM"}}]
La consola procesará automáticamente esta directiva contra el servidor local seguro si el usuario ha iniciado el puente jarvis_bridge.py. Si no te solicitan manipular el sistema operativo o el calendario directamente, responde con normalidad sin incluir esta directiva.`;

    if (memorySummary) {
      instruction += `\n\nRESUMEN CONTEXTUAL PREVIO DE LA CONVERSACIÓN:\n${memorySummary}`;
    }

    return instruction;
  }

  async generateContent(apiKey, model, systemInstruction, history, stagedFiles = []) {
    if (!apiKey) {
      throw {
        isConfigError: true,
        userMessage: 'Señor, no se ha configurado la clave API de Google Gemini en el sistema.',
        technical: {
          code: 'MISSING_API_KEY',
          status: 'LOCAL_CONFIG_ERROR',
          message: 'Por favor, abra los Ajustes (ícono de engranaje) y proporcione una clave API válida de Google AI Studio.'
        }
      };
    }

    const endpoint = `${this.baseUrl}/models/${model}:generateContent?key=${apiKey}`;
    const contents = [];

    history.forEach(turn => {
      const parts = [];
      if (turn.attachments && turn.attachments.length) {
        turn.attachments.forEach(att => {
          if (att.mimeType.startsWith('image/') || att.mimeType === 'application/pdf') {
            parts.push({
              inlineData: {
                mimeType: att.mimeType,
                data: att.base64
              }
            });
          } else if (att.text) {
            parts.push({
              text: `[ARCHIVO ADJUNTO: ${att.name}]\n${att.text}`
            });
          }
        });
      }
      if (turn.text) {
        parts.push({ text: turn.text });
      }

      contents.push({
        role: turn.role === 'assistant' ? 'model' : 'user',
        parts: parts.length > 0 ? parts : [{ text: '...' }]
      });
    });

    if (stagedFiles && stagedFiles.length > 0 && contents.length > 0) {
      const lastMsg = contents[contents.length - 1];
      if (lastMsg.role === 'user') {
        stagedFiles.forEach(file => {
          if (file.mimeType.startsWith('image/') || file.mimeType === 'application/pdf') {
            lastMsg.parts.unshift({
              inlineData: {
                mimeType: file.mimeType,
                data: file.base64
              }
            });
          } else if (file.text) {
            lastMsg.parts.unshift({
              text: `[ARCHIVO ADJUNTO: ${file.name}]\n${file.text}`
            });
          }
        });
      }
    }

    const payload = {
      systemInstruction: {
        parts: [{ text: systemInstruction }]
      },
      contents: contents,
      generationConfig: {
        temperature: 0.6,
        maxOutputTokens: 3000
      }
    };

    let response;
    try {
      response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    } catch (netErr) {
      throw {
        isConfigError: false,
        userMessage: 'Señor, no ha sido posible establecer comunicación de red con los servidores de Google Gemini.',
        technical: {
          code: 'NETWORK_FETCH_FAILED',
          status: 'CONNECTION_ERROR',
          message: netErr.message || 'Fallo de red o bloqueo de conexión en el navegador.'
        }
      };
    }

    if (!response.ok) {
      let errData;
      try {
        errData = await response.json();
      } catch (e) {
        errData = { error: { message: response.statusText } };
      }

      const geminiErr = errData.error || {};
      let friendlyMsg = 'Señor, el enlace con el núcleo de procesamiento ha devuelto una anomalía técnica.';
      if (response.status === 400) {
        friendlyMsg = 'Señor, la petición ha sido rechazada por parámetros no válidos o clave incorrecta.';
      } else if (response.status === 403) {
        friendlyMsg = 'Señor, la clave API proporcionada no cuenta con permisos para este modelo o ha caducado.';
      } else if (response.status === 429) {
        friendlyMsg = 'Señor, hemos alcanzado el límite de cuota por minuto establecido por Google Gemini.';
      } else if (response.status >= 500) {
        friendlyMsg = 'Señor, los servidores de Google Gemini están experimentando una sobrecarga temporal.';
      }

      throw {
        isConfigError: false,
        userMessage: friendlyMsg,
        technical: {
          code: geminiErr.code || response.status,
          status: geminiErr.status || response.statusText,
          message: geminiErr.message || 'Error no especificado por la API de Gemini.'
        }
      };
    }

    const result = await response.json();
    const candidate = result.candidates && result.candidates[0];
    if (!candidate || !candidate.content || !candidate.content.parts) {
      throw {
        isConfigError: false,
        userMessage: 'Señor, la respuesta recibida no contiene datos legibles en el formato esperado.',
        technical: {
          code: 'EMPTY_CANDIDATE',
          status: 'INVALID_PAYLOAD',
          message: JSON.stringify(result)
        }
      };
    }

    const replyText = candidate.content.parts.map(p => p.text || '').join('\n');
    return {
      text: replyText,
      finishReason: candidate.finishReason,
      usageMetadata: result.usageMetadata
    };
  }

  async summarizeHistory(apiKey, model, messagesToSummarize, currentSummary = '') {
    if (!apiKey || messagesToSummarize.length === 0) return currentSummary;

    const endpoint = `${this.baseUrl}/models/${model}:generateContent?key=${apiKey}`;
    const dialogue = messagesToSummarize.map(m => `${m.role.toUpperCase()}: ${m.text}`).join('\n');

    const prompt = `Condensa el siguiente fragmento de conversación en un resumen cronológico sumamente conciso (máximo 4 párrafos cortos). Conserva datos clave, decisiones técnicas tomadas, archivos mencionados y solicitudes pendientes.
${currentSummary ? `Resumen previo existente:\n${currentSummary}\n\n` : ''}
Diálogo a incorporar:
${dialogue}`;

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{ role: 'user', parts: [{ text: prompt }] }],
          generationConfig: { temperature: 0.2, maxOutputTokens: 600 }
        })
      });
      if (res.ok) {
        const data = await res.json();
        return data.candidates[0].content.parts[0].text;
      }
    } catch (e) {
      console.warn('Fallo en auto-resumen de contexto:', e);
    }
    return currentSummary;
  }
}

// --- 5. OPTIONAL LOCAL OS BRIDGE CLIENT ---
class JarvisBridge {
  constructor() {
    this.port = 8888;
    this.host = 'http://127.0.0.1:8888';
    this.isOnline = false;
    this.enabled = false;
  }

  async checkHealth() {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 1500);
      const res = await fetch(`${this.host}/health`, {
        method: 'GET',
        signal: controller.signal
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        this.isOnline = true;
        this.enabled = true;
        return { online: true, data };
      }
    } catch (e) {
      this.isOnline = false;
    }
    return { online: false, reason: 'offline' };
  }

  async executeAction(action, params = {}) {
    if (!this.isOnline) {
      throw new Error('El puente local OS no está activo. Ejecute jarvis_bridge.py en su terminal.');
    }

    const res = await fetch(`${this.host}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, params })
    });
    return await res.json();
  }
}

// --- 6. MAIN COORDINATOR APPLICATION ---
class JarvisApp {
  static showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const pill = document.createElement('div');
    pill.className = 'toast-pill';
    if (type === 'warning') pill.style.borderColor = 'var(--accent-warning)';
    if (type === 'danger') pill.style.borderColor = 'var(--accent-danger)';

    pill.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
      <span>${Utils.escapeHtml(message)}</span>
    `;
    container.appendChild(pill);
    setTimeout(() => {
      pill.style.opacity = '0';
      pill.style.transform = 'translateY(10px)';
      pill.style.transition = 'all 0.3s ease';
      setTimeout(() => pill.remove(), 300);
    }, 3600);
  }

  constructor() {
    this.db = new JarvisDB();
    this.gemini = new JarvisGemini();
    this.bridge = new JarvisBridge();
    this.currentSessionId = null;
    this.sessions = [];
    this.messages = [];
    this.stagedFiles = [];
    this.isProcessing = false;

    this.canvas = new JarvisCoreCanvas('coreCanvas');
    this.voice = new JarvisVoice(
      (text) => this.handleSpeechInput(text),
      (state) => this.handleVoiceStateChange(state),
      (level) => this.canvas.setAudioActivity(level)
    );

    this.initElements();
    this.bindEvents();
  }

  async start() {
    try {
      await this.db.init();
      await this.loadSettings();
      await this.loadDossier();
      await this.loadSessions();
      await this.updateStorageUsage();
      this.checkBridgeStatus();
      setInterval(() => this.checkBridgeStatus(), 12000);
    } catch (e) {
      console.error('Error inicializando JARVIS:', e);
      JarvisApp.showToast('Error cargando la base de datos local.', 'danger');
    }
  }

  initElements() {
    this.elements = {
      sidebar: document.getElementById('sidebar'),
      collapseSidebarBtn: document.getElementById('collapseSidebarBtn'),
      sidebarExpandHandle: document.getElementById('sidebarExpandHandle'),
      btnNewChat: document.getElementById('btnNewChat'),
      sessionList: document.getElementById('sessionList'),
      sessionListWrapper: document.getElementById('sessionListWrapper'),
      sessionPanelToggle: document.getElementById('sessionPanelToggle'),
      sessionCount: document.getElementById('sessionCount'),
      sessionSearchInput: document.getElementById('sessionSearchInput'),
      openSidebarBtn: document.getElementById('openSidebarBtn'),

      storageLabel: document.getElementById('storageLabel'),
      storageBarFill: document.getElementById('storageBarFill'),
      btnOpenSettings: document.getElementById('btnOpenSettings'),
      btnOpenDossier: document.getElementById('btnOpenDossier'),
      btnOpenGlobalSearch: document.getElementById('btnOpenGlobalSearch'),
      btnQuickBackup: document.getElementById('btnQuickBackup'),

      hudAssistantName: document.getElementById('hudAssistantName'),
      apiStatusDot: document.getElementById('apiStatusDot'),
      apiStatusText: document.getElementById('apiStatusText'),
      bridgeChip: document.getElementById('bridgeChip'),
      bridgeStatusDot: document.getElementById('bridgeStatusDot'),
      bridgeStatusText: document.getElementById('bridgeStatusText'),
      activeModelBadge: document.getElementById('activeModelBadge'),
      btnToggleSpeech: document.getElementById('btnToggleSpeech'),
      speechIconOn: document.getElementById('speechIconOn'),
      speechIconOff: document.getElementById('speechIconOff'),

      coreSection: document.getElementById('coreSection'),
      btnToggleCore: document.getElementById('btnToggleCore'),
      toggleCoreText: document.getElementById('toggleCoreText'),
      coreStatusPill: document.getElementById('coreStatusPill'),
      coreStatusText: document.getElementById('coreStatusText'),

      chatContainer: document.getElementById('chatContainer'),

      chatInput: document.getElementById('chatInput'),
      btnSend: document.getElementById('btnSend'),
      btnMic: document.getElementById('btnMic'),
      btnAttachFile: document.getElementById('btnAttachFile'),
      filePicker: document.getElementById('filePicker'),
      dropOverlay: document.getElementById('dropOverlay'),
      stagedFilesContainer: document.getElementById('stagedFilesContainer'),
      charCountHint: document.getElementById('charCountHint'),
      inputSection: document.getElementById('inputSection'),

      modalSettings: document.getElementById('modalSettings'),
      modalDossier: document.getElementById('modalDossier'),
      modalSearch: document.getElementById('modalSearch'),
      modalBridge: document.getElementById('modalBridge'),

      inputApiKey: document.getElementById('inputApiKey'),
      selectModel: document.getElementById('selectModel'),
      customModelGroup: document.getElementById('customModelGroup'),
      inputCustomModel: document.getElementById('inputCustomModel'),
      inputAssistantName: document.getElementById('inputAssistantName'),
      selectVoice: document.getElementById('selectVoice'),
      btnTestVoice: document.getElementById('btnTestVoice'),
      toggleAutoSpeech: document.getElementById('toggleAutoSpeech'),
      btnExportBackup: document.getElementById('btnExportBackup'),
      btnImportBackup: document.getElementById('btnImportBackup'),
      backupImportInput: document.getElementById('backupImportInput'),
      btnSaveSettings: document.getElementById('btnSaveSettings'),

      dossierCallsign: document.getElementById('dossierCallsign'),
      dossierOccupation: document.getElementById('dossierOccupation'),
      dossierFact1: document.getElementById('dossierFact1'),
      dossierFact2: document.getElementById('dossierFact2'),
      dossierFact3: document.getElementById('dossierFact3'),
      btnSaveDossier: document.getElementById('btnSaveDossier'),

      globalSearchInput: document.getElementById('globalSearchInput'),
      globalSearchResults: document.getElementById('globalSearchResults'),

      toggleBridgeEnabled: document.getElementById('toggleBridgeEnabled'),
      bridgeModalStatusText: document.getElementById('bridgeModalStatusText'),
      btnTestBridge: document.getElementById('btnTestBridge')
    };
  }

  bindEvents() {
    const el = this.elements;

    el.openSidebarBtn.addEventListener('click', () => el.sidebar.classList.add('open'));

    // Desktop sidebar collapse/expand
    el.collapseSidebarBtn.addEventListener('click', () => {
      el.sidebar.classList.add('desktop-collapsed');
      el.sidebarExpandHandle.classList.add('visible');
    });
    el.sidebarExpandHandle.addEventListener('click', () => {
      el.sidebar.classList.remove('desktop-collapsed');
      el.sidebarExpandHandle.classList.remove('visible');
    });

    el.btnNewChat.addEventListener('click', () => this.createNewSession());

    el.sessionPanelToggle.addEventListener('click', () => {
      const wrapper = el.sessionListWrapper;
      const toggle = el.sessionPanelToggle;
      wrapper.classList.toggle('collapsed');
      toggle.classList.toggle('collapsed');
    });

    el.sessionSearchInput.addEventListener('input', (e) => this.filterSessions(e.target.value));

    el.btnToggleCore.addEventListener('click', () => {
      el.coreSection.classList.toggle('collapsed');
      const isCollapsed = el.coreSection.classList.contains('collapsed');
      el.toggleCoreText.textContent = isCollapsed ? 'EXPANDIR' : 'MINIMIZAR';
    });

    el.btnToggleSpeech.addEventListener('click', async () => {
      this.voice.autoSpeech = !this.voice.autoSpeech;
      await this.db.setSetting('autoSpeech', this.voice.autoSpeech);
      this.updateSpeechIcons();
      JarvisApp.showToast(this.voice.autoSpeech ? 'Lectura automática activada.' : 'Lectura automática silenciada.');
    });

    el.chatInput.addEventListener('input', () => {
      this.voice.stopSpeaking();
      el.charCountHint.textContent = `${el.chatInput.value.length} caracteres`;
      el.chatInput.style.height = 'auto';
      el.chatInput.style.height = Math.min(el.chatInput.scrollHeight, 160) + 'px';
    });

    el.chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.handleSendMessage();
      }
    });

    el.btnSend.addEventListener('click', () => this.handleSendMessage());

    el.btnMic.addEventListener('click', () => this.voice.toggleRecording());

    el.btnAttachFile.addEventListener('click', () => el.filePicker.click());
    el.filePicker.addEventListener('change', (e) => this.handleFileSelection(e.target.files));

    window.addEventListener('dragover', (e) => {
      e.preventDefault();
      el.dropOverlay.classList.add('active');
    });
    el.dropOverlay.addEventListener('dragleave', (e) => {
      e.preventDefault();
      el.dropOverlay.classList.remove('active');
    });
    el.dropOverlay.addEventListener('drop', (e) => {
      e.preventDefault();
      el.dropOverlay.classList.remove('active');
      if (e.dataTransfer && e.dataTransfer.files) {
        this.handleFileSelection(e.dataTransfer.files);
      }
    });

    el.btnOpenSettings.addEventListener('click', () => this.openModal('modalSettings'));
    el.btnOpenDossier.addEventListener('click', () => this.openModal('modalDossier'));
    el.btnOpenGlobalSearch.addEventListener('click', () => this.openModal('modalSearch'));
    el.bridgeChip.addEventListener('click', () => this.openModal('modalBridge'));

    document.querySelectorAll('[data-close]').forEach(btn => {
      btn.addEventListener('click', () => {
        const modalId = btn.getAttribute('data-close');
        this.closeModal(modalId);
      });
    });

    el.selectModel.addEventListener('change', () => {
      el.customModelGroup.style.display = el.selectModel.value === 'custom' ? 'flex' : 'none';
    });
    el.btnTestVoice.addEventListener('click', () => this.testVoice());
    el.btnSaveSettings.addEventListener('click', () => this.saveSettings());
    el.btnSaveDossier.addEventListener('click', () => this.saveDossier());

    el.btnQuickBackup.addEventListener('click', () => this.exportBackup());
    el.btnExportBackup.addEventListener('click', () => this.exportBackup());
    el.btnImportBackup.addEventListener('click', () => el.backupImportInput.click());
    el.backupImportInput.addEventListener('change', (e) => this.importBackup(e.target.files[0]));

    el.globalSearchInput.addEventListener('input', (e) => this.executeGlobalSearch(e.target.value));

    el.toggleBridgeEnabled.addEventListener('change', async (e) => {
      this.bridge.enabled = e.target.checked;
      await this.db.setSetting('bridgeEnabled', this.bridge.enabled);
      this.checkBridgeStatus();
    });
    el.btnTestBridge.addEventListener('click', () => this.testBridgeConnection());
  }

  openModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.add('active');
  }

  closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.remove('active');
  }

  updateSpeechIcons() {
    const el = this.elements;
    if (this.voice.autoSpeech) {
      el.speechIconOn.style.display = 'block';
      el.speechIconOff.style.display = 'none';
      el.btnToggleSpeech.style.borderColor = 'var(--cyan-primary)';
    } else {
      el.speechIconOn.style.display = 'none';
      el.speechIconOff.style.display = 'block';
      el.btnToggleSpeech.style.borderColor = 'var(--border-dim)';
    }
  }

  handleVoiceStateChange(state) {
    this.canvas.setState(state);
    const pill = this.elements.coreStatusPill;
    const text = this.elements.coreStatusText;
    const mic = this.elements.btnMic;

    pill.className = `core-status-pill ${state}`;

    if (state === 'listening') {
      text.textContent = 'ESCUCHANDO // ENLACE DE VOZ ACTIVO';
      mic.classList.add('recording');
    } else if (state === 'speaking') {
      text.textContent = 'TRANSMITIENDO // SÍNTESIS DE AUDIO';
      mic.classList.remove('recording');
    } else if (state === 'thinking') {
      text.textContent = 'PROCESANDO // NÚCLEO COGNITIVO';
      mic.classList.remove('recording');
    } else if (state === 'error') {
      text.textContent = 'ALERTA // ANOMALÍA EN EL SISTEMA';
      mic.classList.remove('recording');
    } else {
      text.textContent = 'EN ESPERA // SISTEMAS EN LÍNEA';
      mic.classList.remove('recording');
    }
  }

  handleSpeechInput(transcript) {
    if (!transcript) return;
    this.elements.chatInput.value = transcript;
    this.elements.charCountHint.textContent = `${transcript.length} caracteres`;
    this.handleSendMessage();
  }

  // --- SETTINGS MANAGEMENT ---
  async loadSettings() {
    const el = this.elements;
    this.apiKey = await this.db.getSetting('apiKey', '');
    // Default to Gemini 3.8 Flash for maximum speed and compatibility
    this.model = await this.db.getSetting('model', 'gemini-3.8-flash');
    this.assistantName = await this.db.getSetting('assistantName', 'J.A.R.V.I.S.');
    this.voice.autoSpeech = await this.db.getSetting('autoSpeech', false);
    const savedVoiceName = await this.db.getSetting('voiceName', '');
    this.bridge.enabled = await this.db.getSetting('bridgeEnabled', true);

    el.inputApiKey.value = this.apiKey;
    el.hudAssistantName.textContent = this.assistantName;
    el.inputAssistantName.value = this.assistantName;
    el.activeModelBadge.textContent = this.model;
    el.toggleAutoSpeech.checked = this.voice.autoSpeech;
    el.toggleBridgeEnabled.checked = this.bridge.enabled;
    this.updateSpeechIcons();

    const standardModels = [
      'gemini-flash-lite-latest', 'gemini-flash-latest', 'gemini-pro-latest',
      'gemini-3.8-flash', 'gemini-3.8-pro',
      'gemini-3.5-flash', 'gemini-3.5-pro',
      'gemini-2.5-flash', 'gemini-2.5-pro',
      'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro'
    ];

    if (standardModels.includes(this.model)) {
      el.selectModel.value = this.model;
      el.customModelGroup.style.display = 'none';
    } else {
      el.selectModel.value = 'custom';
      el.customModelGroup.style.display = 'flex';
      el.inputCustomModel.value = this.model;
    }

    setTimeout(() => this.populateVoiceSelect(savedVoiceName), 400);
    this.updateApiStatusChip();
  }

  populateVoiceSelect(savedVoiceName) {
    const voices = this.voice.loadVoices();
    const select = this.elements.selectVoice;
    select.innerHTML = '';

    if (voices.length === 0) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'Voz predeterminada del sistema';
      select.appendChild(opt);
      return;
    }

    voices.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v.name;
      opt.textContent = `${v.name} (${v.lang})${v.default ? ' — Por defecto' : ''}`;
      if (v.name === savedVoiceName) {
        opt.selected = true;
        this.voice.selectedVoice = v;
      }
      select.appendChild(opt);
    });

    if (!this.voice.selectedVoice && voices.length > 0) {
      this.voice.selectedVoice = voices[0];
    }
  }

  testVoice() {
    const select = this.elements.selectVoice;
    const voiceName = select.value;
    const voice = this.voice.voices.find(v => v.name === voiceName);
    if (voice) {
      this.voice.selectedVoice = voice;
      this.voice.speak(`Sistemas en línea, señor. Modulación de voz configurada con éxito.`);
    } else {
      this.voice.speak(`Sistemas en línea, señor. Probando síntesis predeterminada.`);
    }
  }

  async saveSettings() {
    const el = this.elements;
    this.apiKey = el.inputApiKey.value.trim();
    await this.db.setSetting('apiKey', this.apiKey);

    if (el.selectModel.value === 'custom') {
      this.model = el.inputCustomModel.value.trim() || 'gemini-3.8-flash';
    } else {
      this.model = el.selectModel.value;
    }
    await this.db.setSetting('model', this.model);
    el.activeModelBadge.textContent = this.model;

    this.assistantName = el.inputAssistantName.value.trim() || 'J.A.R.V.I.S.';
    await this.db.setSetting('assistantName', this.assistantName);
    el.hudAssistantName.textContent = this.assistantName;

    const voiceName = el.selectVoice.value;
    await this.db.setSetting('voiceName', voiceName);
    this.voice.selectedVoice = this.voice.voices.find(v => v.name === voiceName) || null;

    this.voice.autoSpeech = el.toggleAutoSpeech.checked;
    await this.db.setSetting('autoSpeech', this.voice.autoSpeech);
    this.updateSpeechIcons();

    this.updateApiStatusChip();
    this.closeModal('modalSettings');
    JarvisApp.showToast('Configuración almacenada en la memoria local.');
  }

  updateApiStatusChip() {
    const dot = this.elements.apiStatusDot;
    const text = this.elements.apiStatusText;
    if (this.apiKey) {
      dot.className = 'chip-status-dot';
      text.textContent = 'GEMINI ENLACE ACTIVO';
    } else {
      dot.className = 'chip-status-dot warning';
      text.textContent = 'SIN CLAVE API';
    }
  }

  // --- DOSSIER MANAGEMENT ---
  async loadDossier() {
    const el = this.elements;
    this.profile = await this.db.getSetting('profile', {
      callsign: 'Señor Stark',
      occupation: 'Ingeniero & Creador',
      facts: [
        'Prioriza respuestas directas, con código completo y alta precisión.',
        'Entorno de trabajo local con Windows.',
        'Requiere un trato formal de mayordomo refinado.'
      ]
    });

    el.dossierCallsign.value = this.profile.callsign || '';
    el.dossierOccupation.value = this.profile.occupation || '';
    el.dossierFact1.value = (this.profile.facts && this.profile.facts[0]) || '';
    el.dossierFact2.value = (this.profile.facts && this.profile.facts[1]) || '';
    el.dossierFact3.value = (this.profile.facts && this.profile.facts[2]) || '';
  }

  async saveDossier() {
    const el = this.elements;
    this.profile = {
      callsign: el.dossierCallsign.value.trim() || 'Señor',
      occupation: el.dossierOccupation.value.trim(),
      facts: [
        el.dossierFact1.value.trim(),
        el.dossierFact2.value.trim(),
        el.dossierFact3.value.trim()
      ].filter(f => f.length > 0)
    };

    await this.db.setSetting('profile', this.profile);
    this.closeModal('modalDossier');
    JarvisApp.showToast('Dossier táctico actualizado en memoria permanente.');
  }

  // --- SESSIONS MANAGEMENT ---
  async loadSessions() {
    this.sessions = await this.db.getSessions();
    if (this.sessions.length === 0) {
      await this.createNewSession();
    } else {
      this.renderSessionList();
      await this.switchSession(this.sessions[0].id);
    }
  }

  async createNewSession() {
    const newSession = {
      id: Utils.generateId(),
      title: 'Nueva Sesión',
      summary: '',
      createdAt: Date.now(),
      updatedAt: Date.now()
    };
    await this.db.saveSession(newSession);
    this.sessions.unshift(newSession);
    this.renderSessionList();
    await this.switchSession(newSession.id);
    if (window.innerWidth < 900) {
      this.elements.sidebar.classList.remove('open');
    }
  }

  async switchSession(sessionId) {
    this.currentSessionId = sessionId;
    this.renderSessionList();
    this.messages = await this.db.getMessages(sessionId);
    this.renderChatMessages();
  }

  async deleteSession(sessionId, e) {
    if (e) e.stopPropagation();
    if (this.sessions.length <= 1) {
      JarvisApp.showToast('Debe existir al menos una sesión táctica activa.', 'warning');
      return;
    }

    await this.db.deleteSession(sessionId);
    this.sessions = this.sessions.filter(s => s.id !== sessionId);
    this.renderSessionList();
    if (this.currentSessionId === sessionId) {
      await this.switchSession(this.sessions[0].id);
    }
    await this.updateStorageUsage();
    JarvisApp.showToast('Sesión eliminada de la memoria local.');
  }

  renderSessionList() {
    const list = this.elements.sessionList;
    list.innerHTML = '';

    // Update session count badge
    if (this.elements.sessionCount) {
      this.elements.sessionCount.textContent = this.sessions.length;
    }

    this.sessions.forEach(sess => {
      const item = document.createElement('div');
      item.className = `session-item ${sess.id === this.currentSessionId ? 'active' : ''}`;
      item.innerHTML = `
        <div class="session-title">${Utils.escapeHtml(sess.title)}</div>
        <div class="session-date">${Utils.formatDate(sess.updatedAt)}</div>
        <button class="btn-session-del" title="Eliminar sesión">&times;</button>
      `;
      item.addEventListener('click', () => this.switchSession(sess.id));
      item.querySelector('.btn-session-del').addEventListener('click', (e) => this.deleteSession(sess.id, e));
      list.appendChild(item);
    });
  }

  filterSessions(query) {
    const q = query.toLowerCase().trim();
    const items = this.elements.sessionList.querySelectorAll('.session-item');
    this.sessions.forEach((sess, idx) => {
      const match = sess.title.toLowerCase().includes(q);
      if (items[idx]) {
        items[idx].style.display = match ? 'flex' : 'none';
      }
    });
  }

  // --- CHAT RENDERING ---
  renderChatMessages() {
    const container = this.elements.chatContainer;
    container.innerHTML = '';

    if (this.messages.length === 0) {
      const welcome = document.createElement('div');
      welcome.className = 'chat-welcome';
      welcome.innerHTML = `
        <h2>Sistemas JARVIS // En Línea</h2>
        <p>
          A su servicio, ${Utils.escapeHtml((this.profile && this.profile.callsign) || 'señor')}.
          Todos los módulos locales se encuentran operativos. Sus datos, memoria y claves residen en este dispositivo.
        </p>
        <div class="welcome-badges">
          <span class="welcome-badge">MODO PRIVADO LOCAL</span>
          <span class="welcome-badge">INDEXEDDB PERSISTENTE</span>
          <span class="welcome-badge">SÍNTESIS POR VOZ</span>
          <span class="welcome-badge">GEMINI 3.5 - 3.8 READY</span>
        </div>
      `;
      container.appendChild(welcome);
      return;
    }

    this.messages.forEach(msg => {
      this.appendMessageToDOM(msg, false);
    });

    this.scrollToBottom();
  }

  appendMessageToDOM(msg, scroll = true) {
    const container = this.elements.chatContainer;
    const welcome = container.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    const row = document.createElement('div');
    row.className = `chat-bubble-row ${msg.role}`;
    row.id = `msg_${msg.id}`;

    const isAssistant = msg.role === 'assistant';
    const avatarText = isAssistant ? 'J' : 'U';
    const senderTitle = isAssistant ? (this.assistantName || 'J.A.R.V.I.S.') : ((this.profile && this.profile.callsign) || 'USUARIO');

    let attachmentsHtml = '';
    if (msg.attachments && msg.attachments.length > 0) {
      attachmentsHtml = '<div class="msg-attachment-grid">';
      msg.attachments.forEach(att => {
        if (att.mimeType.startsWith('image/')) {
          attachmentsHtml += `<img src="data:${att.mimeType};base64,${att.base64}" class="msg-image-thumb" alt="${Utils.escapeHtml(att.name)}">`;
        } else if (att.mimeType === 'application/pdf') {
          attachmentsHtml += `<div class="msg-attachment-pill msg-attachment-pdf">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
            <span>${Utils.escapeHtml(att.name)}</span>
          </div>`;
        } else {
          attachmentsHtml += `<div class="msg-attachment-pill">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
            <span>${Utils.escapeHtml(att.name)}</span>
          </div>`;
        }
      });
      attachmentsHtml += '</div>';
    }

    let actionsHtml = '';
    if (isAssistant) {
      actionsHtml = `
        <div class="bubble-tools">
          <button class="btn-bubble-action btn-speak-msg" title="Escuchar respuesta">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path></svg>
            Escuchar
          </button>
          <button class="btn-bubble-action btn-copy-msg" title="Copiar texto">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
            Copiar
          </button>
        </div>
      `;
    }

    row.innerHTML = `
      ${isAssistant ? `<div class="bubble-avatar">${avatarText}</div>` : ''}
      <div class="bubble-wrapper">
        <div class="bubble-header">
          <span class="sender-name">${Utils.escapeHtml(senderTitle)}</span>
          <span>${Utils.formatDate(msg.timestamp)}</span>
        </div>
        <div class="bubble-content">
          ${Utils.renderMarkdown(msg.text)}
          ${attachmentsHtml}
        </div>
        ${actionsHtml}
      </div>
      ${!isAssistant ? `<div class="bubble-avatar">${avatarText}</div>` : ''}
    `;

    if (isAssistant) {
      row.querySelector('.btn-speak-msg').addEventListener('click', () => {
        this.voice.speak(msg.text);
      });
      row.querySelector('.btn-copy-msg').addEventListener('click', () => {
        navigator.clipboard.writeText(msg.text);
        JarvisApp.showToast('Respuesta copiada al portapapeles.');
      });
    }

    container.appendChild(row);

    if (scroll) {
      this.scrollToBottom();
    }
  }

  appendThinkingIndicator() {
    const container = this.elements.chatContainer;
    const thinkingId = 'thinking_' + Date.now();
    const row = document.createElement('div');
    row.className = 'chat-bubble-row assistant';
    row.id = thinkingId;
    row.innerHTML = `
      <div class="bubble-avatar">J</div>
      <div class="bubble-wrapper">
        <div class="thinking-box">
          <div class="thinking-dots">
            <span></span><span></span><span></span>
          </div>
          <span>PROCESANDO ANÁLISIS TÁCTICO EN GEMINI...</span>
        </div>
      </div>
    `;
    container.appendChild(row);
    this.scrollToBottom();
    return thinkingId;
  }

  appendErrorCard(errObj) {
    const container = this.elements.chatContainer;
    const row = document.createElement('div');
    row.className = 'chat-bubble-row assistant';
    row.innerHTML = `
      <div class="bubble-avatar" style="border-color: var(--accent-danger); color: var(--accent-danger);">!</div>
      <div class="bubble-wrapper">
        <div class="bubble-header">
          <span class="sender-name" style="color: var(--accent-danger);">${Utils.escapeHtml(this.assistantName)} // DIAGNÓSTICO</span>
          <span>${Utils.formatDate(Date.now())}</span>
        </div>
        <div class="error-card">
          <div class="error-user-msg">${Utils.escapeHtml(errObj.userMessage)}</div>
          <div class="error-tech-details">CÓDIGO: ${Utils.escapeHtml(String(errObj.technical.code))}
ESTADO: ${Utils.escapeHtml(String(errObj.technical.status))}
DETALLE: ${Utils.escapeHtml(String(errObj.technical.message))}</div>
        </div>
      </div>
    `;
    container.appendChild(row);
    this.scrollToBottom();
  }

  scrollToBottom() {
    const container = this.elements.chatContainer;
    container.scrollTop = container.scrollHeight;
  }

  // --- SEND MESSAGE FLOW ---
  async handleSendMessage() {
    if (this.isProcessing) return;

    const input = this.elements.chatInput;
    const rawText = input.value.trim();
    const staged = [...this.stagedFiles];

    if (!rawText && staged.length === 0) return;

    this.voice.stopSpeaking();

    input.value = '';
    input.style.height = 'auto';
    this.elements.charCountHint.textContent = '0 caracteres';
    this.stagedFiles = [];
    this.renderStagedFiles();

    const userMsg = {
      id: Utils.generateId(),
      sessionId: this.currentSessionId,
      role: 'user',
      text: rawText,
      attachments: staged,
      timestamp: Date.now()
    };

    this.messages.push(userMsg);
    await this.db.saveMessage(userMsg);
    this.appendMessageToDOM(userMsg);
    this.renderSessionList();
    await this.updateStorageUsage();

    this.isProcessing = true;
    this.elements.btnSend.disabled = true;
    this.handleVoiceStateChange('thinking');
    const thinkingId = this.appendThinkingIndicator();

    try {
      const currentSess = this.sessions.find(s => s.id === this.currentSessionId);
      let sessionSummary = currentSess ? currentSess.summary : '';
      const recentTurns = this.messages.slice(-8);

      const systemInstruction = this.gemini.buildSystemInstruction(
        this.profile,
        sessionSummary,
        this.assistantName
      );

      const response = await this.generateWithFallback(
        this.apiKey,
        this.model,
        systemInstruction,
        recentTurns
      );

      const thinkingEl = document.getElementById(thinkingId);
      if (thinkingEl) thinkingEl.remove();

      let finalResponseText = response.text;
      const bridgeMatch = response.text.match(/\[BRIDGE_ACTION:\s*(\{.*?\})\s*\]/);
      if (bridgeMatch) {
        try {
          const actionData = JSON.parse(bridgeMatch[1]);
          if (this.bridge.isOnline) {
            const bridgeResult = await this.bridge.executeAction(actionData.action, actionData.params);
            let bridgeNotice = `\n\n> ⚡ **PUENTE LOCAL OS [EJECUTADO]**: `;
            if (bridgeResult.success) {
              if (actionData.action === 'list_files') {
                const filesSummary = (bridgeResult.files || []).map(f => `${f.is_dir ? '📁' : '📄'} ${f.name}`).join(' | ');
                bridgeNotice += `Archivos en el directorio: ${filesSummary || 'Vacío'}`;
              } else if (actionData.action === 'write_file') {
                bridgeNotice += `Archivo \`${bridgeResult.filename}\` guardado con éxito (${bridgeResult.bytes_written} bytes).`;
              } else if (actionData.action === 'read_file') {
                bridgeNotice += `Lectura de \`${bridgeResult.filename}\` completada:\n\`\`\`\n${bridgeResult.content}\n\`\`\``;
              } else if (actionData.action === 'open_item') {
                bridgeNotice += `Programa o archivo iniciado en su equipo: \`${bridgeResult.opened}\`.`;
              } else if (actionData.action === 'system_diagnostics') {
                bridgeNotice += `SO: ${bridgeResult.os} ${bridgeResult.release} | CPU: ${bridgeResult.processor} | Disco Libre: ${bridgeResult.disk_free_gb} GB / ${bridgeResult.disk_total_gb} GB.`;
              } else if (bridgeResult.formatted) {
                bridgeNotice += `\n${bridgeResult.formatted}`;
              } else if (actionData.action === 'calendar_create' && bridgeResult.event) {
                bridgeNotice += `Evento agendado con éxito: ${bridgeResult.event.summary || 'Nuevo evento'}`;
              } else {
                bridgeNotice += `Operación completada: ${JSON.stringify(bridgeResult)}`;
              }
            } else {
              bridgeNotice += `Error al ejecutar: ${bridgeResult.error}`;
            }
            finalResponseText = finalResponseText.replace(bridgeMatch[0], bridgeNotice);
          } else {
            finalResponseText = finalResponseText.replace(bridgeMatch[0], `\n\n> ⚠️ **PUENTE LOCAL OS DESCONECTADO**: Para que pueda interactuar directamente con sus archivos o programas del equipo, asegúrese de habilitar el puente en Ajustes y ejecutar \`python jarvis_bridge.py\` en su terminal.`);
          }
        } catch (parseErr) {
          console.warn('Error interpretando acción del puente:', parseErr);
        }
      }

      const assistantMsg = {
        id: Utils.generateId(),
        sessionId: this.currentSessionId,
        role: 'assistant',
        text: finalResponseText,
        attachments: [],
        timestamp: Date.now(),
        usage: response.usageMetadata
      };

      this.messages.push(assistantMsg);
      await this.db.saveMessage(assistantMsg);
      this.appendMessageToDOM(assistantMsg);
      await this.updateStorageUsage();

      this.handleVoiceStateChange('idle');

      if (this.voice.autoSpeech) {
        this.voice.speak(finalResponseText);
      }

      if (this.messages.length >= 10 && this.messages.length % 6 === 0) {
        this.triggerBackgroundSummarization(currentSess);
      }

    } catch (err) {
      console.error('Error durante procesamiento JARVIS:', err);
      const thinkingEl = document.getElementById(thinkingId);
      if (thinkingEl) thinkingEl.remove();

      this.handleVoiceStateChange('error');
      if (err.userMessage && err.technical) {
        this.appendErrorCard(err);
      } else {
        this.appendErrorCard({
          userMessage: 'Señor, se ha producido una excepción inesperada en el hilo de ejecución.',
          technical: {
            code: 'UNEXPECTED_FAILURE',
            status: 'CLIENT_ERROR',
            message: err.message || String(err)
          }
        });
      }
    } finally {
      this.isProcessing = false;
      this.elements.btnSend.disabled = false;
    }
  }

  // --- AUTO-FALLBACK: Gemini 3.8 -> 3.5 on rate limit / overload ---
  async generateWithFallback(apiKey, primaryModel, systemInstruction, history) {
    const fallbackMap = {
      'gemini-3.8-flash': 'gemini-3.5-flash',
      'gemini-3.8-pro': 'gemini-3.5-pro'
    };

    try {
      return await this.gemini.generateContent(apiKey, primaryModel, systemInstruction, history, []);
    } catch (err) {
      const code = err.technical && (err.technical.code || err.technical.status);
      const isRateLimit = code === 429 || code === '429' || String(code).includes('RESOURCE_EXHAUSTED');
      const isOverload = code === 503 || code === '503' || String(code).includes('UNAVAILABLE');

      const fallbackModel = fallbackMap[primaryModel];

      if ((isRateLimit || isOverload) && fallbackModel) {
        console.warn(`[JARVIS] Modelo ${primaryModel} sobrecargado (${code}). Reintentando con ${fallbackModel}...`);
        JarvisApp.showToast(`Tráfico elevado en ${primaryModel}. Redirigiendo a ${fallbackModel}...`, 'warning');
        this.elements.activeModelBadge.textContent = fallbackModel + ' (auto)';

        try {
          const fallbackResponse = await this.gemini.generateContent(apiKey, fallbackModel, systemInstruction, history, []);
          // Restore original badge after successful fallback
          setTimeout(() => {
            this.elements.activeModelBadge.textContent = primaryModel;
          }, 5000);
          return fallbackResponse;
        } catch (fallbackErr) {
          // Restore badge and throw original or fallback error
          this.elements.activeModelBadge.textContent = primaryModel;
          throw fallbackErr;
        }
      }

      throw err;
    }
  }

  async triggerBackgroundSummarization(session) {
    if (!session || !this.apiKey) return;
    try {
      const toSummarize = this.messages.slice(0, -6);
      if (toSummarize.length < 4) return;

      const newSummary = await this.gemini.summarizeHistory(
        this.apiKey,
        this.model,
        toSummarize,
        session.summary
      );

      if (newSummary && newSummary !== session.summary) {
        session.summary = newSummary;
        await this.db.saveSession(session);
        console.log('Contexto resumido y compactado automáticamente para la sesión:', session.id);
      }
    } catch (e) {
      console.warn('Error en resumen en segundo plano:', e);
    }
  }

  // --- ATTACHMENTS HANDLING ---
  async handleFileSelection(fileList) {
    if (!fileList || fileList.length === 0) return;

    for (let i = 0; i < fileList.length; i++) {
      const file = fileList[i];
      const isImage = file.type.startsWith('image/');
      const isPdf = file.type === 'application/pdf' || /\.pdf$/i.test(file.name);
      const isText = file.type.startsWith('text/') || 
                     /\.(txt|py|js|json|html|css|md|csv|log|xml|c|cpp|h|java|sql)$/i.test(file.name);

      if (isImage) {
        const base64 = await this.readFileAsBase64(file);
        this.stagedFiles.push({
          name: file.name,
          mimeType: file.type || 'image/png',
          size: file.size,
          base64: base64
        });
      } else if (isPdf) {
        const base64 = await this.readFileAsBase64(file);
        this.stagedFiles.push({
          name: file.name,
          mimeType: 'application/pdf',
          size: file.size,
          base64: base64
        });
      } else if (isText) {
        const textContent = await this.readFileAsText(file);
        this.stagedFiles.push({
          name: file.name,
          mimeType: file.type || 'text/plain',
          size: file.size,
          text: textContent
        });
      } else {
        JarvisApp.showToast(`Archivo "${file.name}" no soportado en este modo. Se admiten imágenes, PDF, texto y código.`, 'warning');
      }
    }

    this.renderStagedFiles();
    this.elements.filePicker.value = '';
  }

  readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const base64String = reader.result.split(',')[1];
        resolve(base64String);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  readFileAsText(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsText(file);
    });
  }

  renderStagedFiles() {
    const container = this.elements.stagedFilesContainer;
    container.innerHTML = '';

    this.stagedFiles.forEach((file, idx) => {
      const chip = document.createElement('div');
      chip.className = 'staged-file-chip';
      chip.innerHTML = `
        <span>${Utils.escapeHtml(file.name)} (${Utils.formatBytes(file.size)})</span>
        <button class="btn-remove-file" title="Quitar archivo">&times;</button>
      `;
      chip.querySelector('.btn-remove-file').addEventListener('click', () => {
        this.stagedFiles.splice(idx, 1);
        this.renderStagedFiles();
      });
      container.appendChild(chip);
    });
  }

  // --- STORAGE METER & QUOTA ---
  async updateStorageUsage() {
    try {
      const bytesUsed = await this.db.calculateStorageUsage();
      const logicalMaxBytes = 20 * 1024 * 1024 * 1024; // 20 GB logical limit
      const percent = Math.min((bytesUsed / logicalMaxBytes) * 100, 100);

      this.elements.storageLabel.textContent = `${Utils.formatBytes(bytesUsed)} / 20 GB`;
      this.elements.storageBarFill.style.width = Math.max(percent, 1.5) + '%';

      if (bytesUsed > 50 * 1024 * 1024) {
        this.elements.storageBarFill.style.background = 'var(--accent-warning)';
      } else {
        this.elements.storageBarFill.style.background = 'linear-gradient(90deg, var(--cyan-dim), var(--cyan-primary))';
      }
    } catch (e) {
      console.warn('Error calculando espacio:', e);
    }
  }

  // --- BACKUP EXPORT & IMPORT ---
  async exportBackup() {
    try {
      const backupData = await this.db.exportFullBackup();
      const blob = new Blob([JSON.stringify(backupData, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const dateStr = new Date().toISOString().slice(0, 10);
      a.href = url;
      a.download = `JARVIS_Backup_${dateStr}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      JarvisApp.showToast('Copia de seguridad exportada con éxito.');
    } catch (e) {
      console.error('Error exportando respaldo:', e);
      JarvisApp.showToast('Error generando copia de seguridad.', 'danger');
    }
  }

  async importBackup(file) {
    if (!file) return;
    try {
      const text = await this.readFileAsText(file);
      const data = JSON.parse(text);
      await this.db.importFullBackup(data);
      JarvisApp.showToast('Copia restaurada con éxito. Actualizando consola...');
      setTimeout(() => window.location.reload(), 1200);
    } catch (e) {
      console.error('Error importando copia:', e);
      JarvisApp.showToast(`Error al restaurar: ${e.message}`, 'danger');
    } finally {
      this.elements.backupImportInput.value = '';
    }
  }

  // --- GLOBAL SEARCH ---
  async executeGlobalSearch(query) {
    const q = query.trim().toLowerCase();
    const resultsContainer = this.elements.globalSearchResults;

    if (!q || q.length < 2) {
      resultsContainer.innerHTML = `
        <div style="text-align: center; color: var(--text-dim); padding: 30px; font-family: var(--font-hud); font-size: 12px;">
          INTRODUZCA AL MENOS 2 CARACTERES PARA ESCANEAR EL HISTORIAL
        </div>
      `;
      return;
    }

    const allMsgs = await this.db.getAllMessages();
    const matchingMsgs = allMsgs.filter(m => m.text && m.text.toLowerCase().includes(q));

    if (matchingMsgs.length === 0) {
      resultsContainer.innerHTML = `
        <div style="text-align: center; color: var(--text-dim); padding: 30px; font-family: var(--font-hud); font-size: 12px;">
          NO SE ENCONTRARON COINCIDENCIAS PARA "${Utils.escapeHtml(q)}"
        </div>
      `;
      return;
    }

    resultsContainer.innerHTML = '';
    matchingMsgs.forEach(m => {
      const sess = this.sessions.find(s => s.id === m.sessionId);
      const sessTitle = sess ? sess.title : 'Sesión desconocida';

      const lower = m.text.toLowerCase();
      const matchIdx = lower.indexOf(q);
      const start = Math.max(0, matchIdx - 40);
      const end = Math.min(m.text.length, matchIdx + q.length + 40);
      let snippet = m.text.substring(start, end);
      if (start > 0) snippet = '...' + snippet;
      if (end < m.text.length) snippet = snippet + '...';

      const highlightedSnippet = Utils.escapeHtml(snippet).replace(
        new RegExp(Utils.escapeHtml(q), 'gi'),
        (match) => `<span class="search-highlight">${match}</span>`
      );

      const item = document.createElement('div');
      item.className = 'search-result-item';
      item.innerHTML = `
        <div class="search-result-meta">
          <span>${Utils.escapeHtml(sessTitle)} // [${m.role.toUpperCase()}]</span>
          <span>${Utils.formatDate(m.timestamp)}</span>
        </div>
        <div class="search-result-snippet">${highlightedSnippet}</div>
      `;
      item.addEventListener('click', async () => {
        this.closeModal('modalSearch');
        await this.switchSession(m.sessionId);
        const bubbleEl = document.getElementById(`msg_${m.id}`);
        if (bubbleEl) {
          bubbleEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
          bubbleEl.style.boxShadow = '0 0 20px var(--cyan-primary)';
          setTimeout(() => { bubbleEl.style.boxShadow = ''; }, 2500);
        }
      });
      resultsContainer.appendChild(item);
    });
  }

  // --- BRIDGE HEALTH & TESTING ---
  async checkBridgeStatus() {
    const dot = this.elements.bridgeStatusDot;
    const text = this.elements.bridgeStatusText;
    const modalText = this.elements.bridgeModalStatusText;

    if (!this.bridge.enabled) {
      dot.className = 'chip-status-dot offline';
      text.textContent = 'PUENTE OS: AISLADO';
      modalText.textContent = 'DESHABILITADO EN AJUSTES';
      modalText.style.color = 'var(--text-dim)';
      return;
    }

    const health = await this.bridge.checkHealth();
    if (health.online) {
      dot.className = 'chip-status-dot';
      text.textContent = 'PUENTE OS: EN LÍNEA';
      modalText.textContent = 'EN LÍNEA (CONECTADO A 127.0.0.1:8888)';
      modalText.style.color = 'var(--accent-success)';
    } else {
      dot.className = 'chip-status-dot warning';
      text.textContent = 'PUENTE OS: OFFLINE';
      modalText.textContent = 'DESCONECTADO (SCRIPT NO DETECTADO)';
      modalText.style.color = 'var(--accent-danger)';
    }
  }

  async testBridgeConnection() {
    if (!this.bridge.enabled) {
      JarvisApp.showToast('Primero active la casilla del puente en este panel.', 'warning');
      return;
    }
    JarvisApp.showToast('Comprobando enlace con 127.0.0.1:8888...');
    await this.checkBridgeStatus();
    if (this.bridge.isOnline) {
      JarvisApp.showToast('¡Enlace con jarvis_bridge.py establecido exitosamente!');
    } else {
      JarvisApp.showToast('No se pudo conectar. Asegúrese de ejecutar "python jarvis_bridge.py".', 'danger');
    }
  }
}

// --- BOOTSTRAP ---
window.addEventListener('DOMContentLoaded', () => {
  window.JarvisAppInstance = new JarvisApp();
  window.JarvisAppInstance.start();
});
