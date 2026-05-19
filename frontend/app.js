/**
 * LangGraph Live Voice - Frontend Application
 * Handles microphone capture, WebSocket communication, and audio playback.
 */

class LiveVoiceApp {
    constructor() {
        // DOM elements
        this.connectBtn = document.getElementById('connectBtn');
        this.disconnectBtn = document.getElementById('disconnectBtn');
        this.statusDot = document.getElementById('statusDot');
        this.statusText = document.getElementById('statusText');
        this.transcript = document.getElementById('transcript');
        this.toolActivity = document.getElementById('toolActivity');
        this.speakingIndicator = document.getElementById('speakingIndicator');
        this.canvas = document.getElementById('audioVisualizer');
        this.canvasCtx = this.canvas.getContext('2d');
        this.updateSettingsBtn = document.getElementById('updateSettingsBtn');
        this.instructionsInput = document.getElementById('instructions');

        // State
        this.ws = null;
        this.mediaStream = null;
        this.audioContext = null;
        this.scriptProcessor = null;
        this.playbackQueue = [];
        this.isPlaying = false;
        this.analyser = null;
        this.animationFrame = null;
        this.currentAssistantMessage = null;
        this.currentUserMessage = null;

        this.resetBtn = document.getElementById('resetBtn');

        // Bind events
        this.connectBtn.addEventListener('click', () => this.connect());
        this.disconnectBtn.addEventListener('click', () => this.disconnect());
        this.resetBtn.addEventListener('click', () => this.resetSession());
        this.updateSettingsBtn.addEventListener('click', () => this.updateSettings());

        // Slider value displays
        this._bindSlider('vadThreshold', 'vadThresholdValue');
        this._bindSlider('silenceDuration', 'silenceDurationValue', 'ms');

        // Show/hide Foundry-only options based on client mode
        const clientModeSelect = document.getElementById('clientMode');
        clientModeSelect.addEventListener('change', () => this._updateFoundryOptions());
        this._updateFoundryOptions();

        // Initialize visualizer
        this.drawIdleVisualizer();
    }

    _bindSlider(sliderId, displayId, suffix = '') {
        const slider = document.getElementById(sliderId);
        const display = document.getElementById(displayId);
        if (slider && display) {
            slider.addEventListener('input', () => {
                display.textContent = slider.value + suffix;
            });
        }
    }

    _updateFoundryOptions() {
        const mode = document.getElementById('clientMode').value;
        const isFoundryLike = mode === 'foundry' || mode === 'agent';
        document.querySelectorAll('.foundry-only-option').forEach(el => {
            el.style.opacity = isFoundryLike ? '1' : '0.4';
        });
        document.querySelectorAll('.foundry-only-option input').forEach(el => {
            el.disabled = !isFoundryLike;
        });
        const semanticOpt = document.querySelector('#turnDetection option[value="semantic_vad"]');
        if (semanticOpt) semanticOpt.disabled = !isFoundryLike;
        if (!isFoundryLike && document.getElementById('turnDetection').value === 'semantic_vad') {
            document.getElementById('turnDetection').value = 'server_vad';
        }
    }

    setStatus(status, text) {
        this.statusDot.className = `status-dot ${status}`;
        this.statusText.textContent = text;
    }

    async connect() {
        try {
            this.setStatus('connecting', 'Connecting...');
            this.connectBtn.disabled = true;
            document.getElementById('clientMode').disabled = true;
            document.getElementById('voiceSelect').disabled = true;

            // Request microphone access
            this.mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: 24000,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                }
            });

            // Set up audio context for capturing
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
                sampleRate: 24000,
            });
            // Ensure audio context is running (may be suspended if not from user gesture)
            if (this.audioContext.state === 'suspended') {
                await this.audioContext.resume();
            }

            const source = this.audioContext.createMediaStreamSource(this.mediaStream);

            // Create analyser for visualization
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 256;
            source.connect(this.analyser);

            // Use ScriptProcessorNode to capture raw PCM data
            // (AudioWorklet would be better for production but adds complexity)
            this.scriptProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);
            source.connect(this.scriptProcessor);
            this.scriptProcessor.connect(this.audioContext.destination);

            this.scriptProcessor.onaudioprocess = (event) => {
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                    const inputData = event.inputBuffer.getChannelData(0);
                    const pcm16 = this.float32ToPcm16(inputData);
                    const base64 = this.arrayBufferToBase64(pcm16.buffer);
                    this.ws.send(JSON.stringify({
                        type: 'audio.append',
                        audio: base64,
                    }));
                }
            };

            // Connect WebSocket
            this._lastError = null;
            const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const clientMode = document.getElementById('clientMode')?.value || 'websocket';
            const voice = document.getElementById('voiceSelect')?.value || 'alloy';
            const turnDetection = document.getElementById('turnDetection')?.value || 'server_vad';
            const vadThreshold = document.getElementById('vadThreshold')?.value || '0.5';
            const silenceDuration = document.getElementById('silenceDuration')?.value || '500';
            const maxTokens = document.getElementById('maxTokens')?.value || 'inf';
            const noiseReduction = document.getElementById('noiseReduction')?.checked ? '1' : '0';
            const echoCancellation = document.getElementById('echoCancellation')?.checked ? '1' : '0';

            const params = new URLSearchParams({
                client: clientMode,
                voice: voice,
                turn_detection: turnDetection,
                vad_threshold: vadThreshold,
                silence_duration: silenceDuration,
                max_tokens: maxTokens,
                noise_reduction: noiseReduction,
                echo_cancellation: echoCancellation,
            });
            const wsUrl = `${wsProtocol}//${window.location.host}/ws/audio?${params}`;
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                this.setStatus('connected', 'Connected - Speak to start');
                this.disconnectBtn.disabled = false;
                this.resetBtn.disabled = false;
                this.startVisualizer();
            };

            this.ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                this.handleServerMessage(data);
            };

            this.ws.onclose = () => {
                if (!this._lastError) {
                    this.setStatus('', 'Disconnected');
                }
                this.cleanup();
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                if (!this._lastError) {
                    this.setStatus('', 'Connection error');
                }
                this.cleanup();
            };

        } catch (error) {
            console.error('Connection failed:', error);
            this.setStatus('', `Error: ${error.message}`);
            this.connectBtn.disabled = false;
        }
    }

    disconnect() {
        if (this.ws) {
            // Prevent onclose from calling cleanup again
            this.ws.onclose = null;
            this.ws.onerror = null;
            this.ws.close();
            this.ws = null;
        }
        this.cleanup();
    }

    resetSession() {
        // Clear UI
        this.transcript.innerHTML = '';
        this.toolActivity.innerHTML = '<p class="placeholder">Tool calls will appear here...</p>';
        this.currentAssistantMessage = null;
        this.currentUserMessage = null;
        this.playbackQueue = [];
        this.isPlaying = false;
        // Disconnect and reconnect to get a fresh server-side session
        const wasConnected = this.ws && this.ws.readyState === WebSocket.OPEN;
        if (wasConnected) {
            this.ws.onclose = () => {
                this.ws = null;
                this.setStatus('connecting', 'Reconnecting...');
                this.transcript.innerHTML = '';
                // Clean up audio resources so connect() can recreate them
                if (this.scriptProcessor) { this.scriptProcessor.disconnect(); this.scriptProcessor = null; }
                if (this.audioContext) { this.audioContext.close(); this.audioContext = null; }
                if (this.mediaStream) { this.mediaStream.getTracks().forEach(t => t.stop()); this.mediaStream = null; }
                if (this.animationFrame) { cancelAnimationFrame(this.animationFrame); this.animationFrame = null; }
                this.connect();
            };
            this.ws.close();
        }
    }

    cleanup() {
        if (this.scriptProcessor) {
            this.scriptProcessor.disconnect();
            this.scriptProcessor = null;
        }
        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(track => track.stop());
            this.mediaStream = null;
        }
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
            this.animationFrame = null;
        }
        this.playbackQueue = [];
        this.isPlaying = false;

        this.connectBtn.disabled = false;
        this.disconnectBtn.disabled = true;
        this.resetBtn.disabled = true;
        document.getElementById('clientMode').disabled = false;
        document.getElementById('voiceSelect').disabled = false;
        this.speakingIndicator.classList.remove('active');
        this.drawIdleVisualizer();
    }

    handleServerMessage(data) {
        switch (data.type) {
            case 'session.created':
            case 'session.updated':
                this.addSystemMessage(data.message);
                break;

            case 'audio.delta':
                this.playAudioChunk(data.audio);
                break;

            case 'transcript.delta':
                if (data.role === 'assistant') {
                    this.appendAssistantDelta(data.delta);
                } else if (data.role === 'user') {
                    this.appendUserDelta(data.delta);
                }
                break;

            case 'transcript.done':
                this.finalizeTranscript(data.transcript, data.role);
                break;

            case 'speech.started':
                this.speakingIndicator.classList.add('active');
                this.setStatus('connected', 'Listening...');
                break;

            case 'speech.stopped':
                this.speakingIndicator.classList.remove('active');
                this.setStatus('connected', 'Processing...');
                break;

            case 'tool.calling':
                this.showToolCall(data.name, data.arguments);
                break;

            case 'tool.result':
                this.showToolResult(data.name, data.result);
                break;

            case 'response.done':
                this.setStatus('connected', 'Connected - Speak to continue');
                this.currentAssistantMessage = null;
                break;

            case 'error':
                this._lastError = data.message;
                this.setStatus('error', data.message);
                this.addSystemMessage(`⚠️ ${data.message}`);
                break;
        }
    }

    appendAssistantDelta(delta) {
        if (!this.currentAssistantMessage) {
            this.currentAssistantMessage = this.addTranscriptMessage('', 'assistant');
        }
        const contentEl = this.currentAssistantMessage.querySelector('.content');
        contentEl.textContent += delta;
        this.scrollTranscript();
    }

    appendUserDelta(delta) {
        if (!this.currentUserMessage) {
            // Insert user message before the current assistant message if one exists
            this.currentUserMessage = this.insertTranscriptMessageBefore('', 'user', this.currentAssistantMessage);
        }
        const contentEl = this.currentUserMessage.querySelector('.content');
        contentEl.textContent += delta;
        this.scrollTranscript();
    }

    finalizeTranscript(text, role) {
        if (role === 'user') {
            if (this.currentUserMessage) {
                if (text) {
                    const contentEl = this.currentUserMessage.querySelector('.content');
                    contentEl.textContent = text;
                }
                this.currentUserMessage = null;
            } else if (text) {
                // Insert before current assistant message if it exists
                this.insertTranscriptMessageBefore(text, 'user', this.currentAssistantMessage);
            }
        } else if (role === 'assistant') {
            if (this.currentAssistantMessage) {
                if (text) {
                    const contentEl = this.currentAssistantMessage.querySelector('.content');
                    contentEl.textContent = text;
                }
                this.currentAssistantMessage = null;
            } else if (text) {
                this.addTranscriptMessage(text, 'assistant');
            }
        }
    }

    addTranscriptMessage(text, role) {
        const div = document.createElement('div');
        div.className = `transcript-message ${role}`;
        div.innerHTML = `
            <div class="role">${role}</div>
            <div class="content">${text}</div>
        `;
        this.transcript.appendChild(div);
        this.scrollTranscript();
        return div;
    }

    insertTranscriptMessageBefore(text, role, beforeElement) {
        const div = document.createElement('div');
        div.className = `transcript-message ${role}`;
        div.innerHTML = `
            <div class="role">${role}</div>
            <div class="content">${text}</div>
        `;
        if (beforeElement && beforeElement.parentNode === this.transcript) {
            this.transcript.insertBefore(div, beforeElement);
        } else {
            this.transcript.appendChild(div);
        }
        this.scrollTranscript();
        return div;
    }

    addSystemMessage(text) {
        const div = document.createElement('div');
        div.className = 'transcript-message system';
        div.style.cssText = 'align-self: center; background: transparent; color: var(--text-muted); font-size: 0.85rem; font-style: italic;';
        div.textContent = text;
        this.transcript.appendChild(div);
        this.scrollTranscript();
    }

    scrollTranscript() {
        this.transcript.scrollTop = this.transcript.scrollHeight;
    }

    showToolCall(name, args) {
        // Remove placeholder
        const placeholder = this.toolActivity.querySelector('.placeholder');
        if (placeholder) placeholder.remove();

        const div = document.createElement('div');
        div.className = 'tool-item';
        div.id = `tool-${name}-${Date.now()}`;
        div.innerHTML = `<span class="tool-name">⚡ ${name}</span> <span class="tool-args">${args}</span>`;
        this.toolActivity.appendChild(div);
        this.toolActivity.scrollTop = this.toolActivity.scrollHeight;
    }

    showToolResult(name, result) {
        const items = this.toolActivity.querySelectorAll('.tool-item:not(.completed)');
        const lastItem = items[items.length - 1];
        if (lastItem) {
            lastItem.classList.add('completed');
            lastItem.innerHTML = `<span class="tool-name">✓ ${name}</span> → ${result}`;
        }
    }

    // Audio playback using Web Audio API
    async playAudioChunk(base64Audio) {
        if (!this.audioContext) return;
        if (this.audioContext.state === 'suspended') {
            await this.audioContext.resume();
        }

        const pcm16 = this.base64ToArrayBuffer(base64Audio);
        const float32 = this.pcm16ToFloat32(new Int16Array(pcm16));

        const audioBuffer = this.audioContext.createBuffer(1, float32.length, 24000);
        audioBuffer.getChannelData(0).set(float32);

        this.playbackQueue.push(audioBuffer);
        if (!this.isPlaying) {
            this.playNextChunk();
        }
    }

    playNextChunk() {
        if (this.playbackQueue.length === 0) {
            this.isPlaying = false;
            return;
        }

        this.isPlaying = true;
        const buffer = this.playbackQueue.shift();
        const source = this.audioContext.createBufferSource();
        source.buffer = buffer;
        source.connect(this.audioContext.destination);
        source.onended = () => this.playNextChunk();
        source.start();
    }

    // Audio format conversion utilities
    float32ToPcm16(float32Array) {
        const pcm16 = new Int16Array(float32Array.length);
        for (let i = 0; i < float32Array.length; i++) {
            const s = Math.max(-1, Math.min(1, float32Array[i]));
            pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        return pcm16;
    }

    pcm16ToFloat32(pcm16Array) {
        const float32 = new Float32Array(pcm16Array.length);
        for (let i = 0; i < pcm16Array.length; i++) {
            float32[i] = pcm16Array[i] / (pcm16Array[i] < 0 ? 0x8000 : 0x7FFF);
        }
        return float32;
    }

    arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.length; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    }

    base64ToArrayBuffer(base64) {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }

    // Audio visualizer
    startVisualizer() {
        const draw = () => {
            this.animationFrame = requestAnimationFrame(draw);

            if (!this.analyser) return;

            const bufferLength = this.analyser.frequencyBinCount;
            const dataArray = new Uint8Array(bufferLength);
            this.analyser.getByteFrequencyData(dataArray);

            const width = this.canvas.width;
            const height = this.canvas.height;
            this.canvasCtx.fillStyle = '#1e293b';
            this.canvasCtx.fillRect(0, 0, width, height);

            const barWidth = (width / bufferLength) * 2.5;
            let x = 0;

            for (let i = 0; i < bufferLength; i++) {
                const barHeight = (dataArray[i] / 255) * height;
                const gradient = this.canvasCtx.createLinearGradient(0, height, 0, height - barHeight);
                gradient.addColorStop(0, '#2563eb');
                gradient.addColorStop(1, '#10b981');
                this.canvasCtx.fillStyle = gradient;
                this.canvasCtx.fillRect(x, height - barHeight, barWidth - 1, barHeight);
                x += barWidth;
            }
        };
        draw();
    }

    drawIdleVisualizer() {
        const width = this.canvas.width;
        const height = this.canvas.height;
        this.canvasCtx.fillStyle = '#1e293b';
        this.canvasCtx.fillRect(0, 0, width, height);

        // Draw a flat line
        this.canvasCtx.strokeStyle = '#475569';
        this.canvasCtx.lineWidth = 2;
        this.canvasCtx.beginPath();
        this.canvasCtx.moveTo(0, height / 2);
        this.canvasCtx.lineTo(width, height / 2);
        this.canvasCtx.stroke();
    }

    updateSettings() {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this._flashButton(this.updateSettingsBtn, 'Not connected', '#dc2626');
            return;
        }

        const payload = {
            type: 'session.update',
            instructions: this.instructionsInput.value.trim(),
            voice: document.getElementById('voiceSelect')?.value || 'alloy',
            turn_detection: document.getElementById('turnDetection')?.value || 'server_vad',
            vad_threshold: parseFloat(document.getElementById('vadThreshold')?.value || '0.5'),
            silence_duration: parseInt(document.getElementById('silenceDuration')?.value || '500'),
            noise_reduction: document.getElementById('noiseReduction')?.checked || false,
            echo_cancellation: document.getElementById('echoCancellation')?.checked || false,
        };

        this.ws.send(JSON.stringify(payload));
        this.addSystemMessage('Session settings updated');
        this._flashButton(this.updateSettingsBtn, '✓ Updated', 'var(--success)');
    }

    _flashButton(btn, text, color) {
        const originalText = btn.textContent;
        const originalBg = btn.style.backgroundColor;
        const originalColor = btn.style.color;
        btn.textContent = text;
        btn.style.backgroundColor = color;
        btn.style.color = '#fff';
        btn.disabled = true;
        setTimeout(() => {
            btn.textContent = originalText;
            btn.style.backgroundColor = originalBg;
            btn.style.color = originalColor;
            btn.disabled = false;
        }, 1500);
    }
}

// Initialize the app
document.addEventListener('DOMContentLoaded', () => {
    new LiveVoiceApp();
});
