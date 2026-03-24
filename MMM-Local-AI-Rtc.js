/* global Module */

Module.register("MMM-Local-AI-Rtc", {
    defaults: {
        updateInterval: 80,
        animationSpeed: 400,
        idleTimeout: 30000,
        fadeDuration: 600,
        minScale: 0.92,
        maxScale: 1.18,
        glowStrength: 20,
        bubbleSize: 180,
        label: "",
        bridge: {
            enabled: true,
            host: "127.0.0.1",
            port: 3210,
            token: "",
            path: "/api/events"
        },
        notifications: {
            state: "LOCAL_AI_RTC_STATE",
            active: "LOCAL_AI_RTC_ACTIVE",
            inactive: "LOCAL_AI_RTC_INACTIVE",
            speaking: "LOCAL_AI_RTC_SPEAKING",
            idle: "LOCAL_AI_RTC_IDLE",
            level: "LOCAL_AI_RTC_LEVEL"
        }
    },

    start: function () {
        this.active = false;
        this.speaking = false;
        this.level = 0;
        this.visualLevel = 0;
        this.phase = 0;
        this.lastRtcEventAt = 0;
        this.frameTimer = null;
        this.startedAt = Date.now();
        this.domReady = false;
        this.registerBridge();
        this.startAnimationLoop();
    },

    getStyles: function () {
        return ["MMM-Local-AI-Rtc.css"];
    },

    getDom: function () {
        const wrapper = document.createElement("div");
        wrapper.className = "mmm-local-ai-rtc";

        const bubble = document.createElement("div");
        bubble.className = "mmm-local-ai-rtc__bubble";
        bubble.style.setProperty("--bubble-size", this.config.bubbleSize + "px");
        bubble.style.setProperty("--fade-duration", this.config.fadeDuration + "ms");

        const core = document.createElement("div");
        core.className = "mmm-local-ai-rtc__core";

        const ring = document.createElement("div");
        ring.className = "mmm-local-ai-rtc__ring";

        const sheen = document.createElement("div");
        sheen.className = "mmm-local-ai-rtc__sheen";

        bubble.appendChild(ring);
        bubble.appendChild(core);
        bubble.appendChild(sheen);
        wrapper.appendChild(bubble);

        if (this.config.label) {
            const label = document.createElement("div");
            label.className = "mmm-local-ai-rtc__label";
            label.innerHTML = this.config.label;
            wrapper.appendChild(label);
        }

        this.wrapperEl = wrapper;
        this.bubbleEl = bubble;
        this.domReady = true;
        this.renderState();

        return wrapper;
    },

    notificationReceived: function (notification, payload) {
        const notifications = this.config.notifications;

        if (notification === notifications.state) {
            this.applyStatePayload(payload);
            return;
        }

        if (notification === notifications.active) {
            this.markRtcActive();
            if (payload !== undefined) {
                this.applyStatePayload(payload, { keepExisting: true });
            } else {
                this.setActive(true);
            }
            return;
        }

        if (notification === notifications.inactive || notification === notifications.idle) {
            this.applyInactivePayload(payload);
            return;
        }

        if (notification === notifications.speaking) {
            this.markRtcActive();
            this.applySpeakingPayload(payload);
            return;
        }

        if (notification === notifications.level) {
            this.markRtcActive();
            this.level = this.normalizeLevel(payload);
            if (this.level > 0.02) {
                this.active = true;
                this.speaking = true;
            }
            this.renderState();
        }
    },

    socketNotificationReceived: function (notification, payload) {
        if (notification !== "MMM_LOCAL_AI_RTC_EVENT") {
            return;
        }

        if (!payload || payload.identifier !== this.identifier) {
            return;
        }

        this.handleBridgeEvent(payload.event || {});
    },

    applyStatePayload: function (payload, options) {
        const keepExisting = options && options.keepExisting;

        if (typeof payload === "boolean") {
            this.markRtcActive();
            this.setActive(payload);
            this.setSpeaking(payload);
            if (!payload) {
                this.level = 0;
            }
            return;
        }

        if (!payload || typeof payload !== "object") {
            if (!keepExisting) {
                this.markRtcActive();
                this.setActive(true);
            }
            return;
        }

        if (payload.called || payload.visible || payload.active || payload.speaking || this.normalizeLevel(payload.level) > 0) {
            this.markRtcActive();
        }

        if (typeof payload.active === "boolean") {
            this.active = payload.active;
        } else if (!keepExisting && (payload.called || payload.visible)) {
            this.active = true;
        }

        if (typeof payload.speaking === "boolean") {
            this.speaking = payload.speaking;
        }

        if (payload.level !== undefined) {
            this.level = this.normalizeLevel(payload.level);
            if (this.level > 0.02) {
                this.active = true;
                if (payload.speaking === undefined) {
                    this.speaking = true;
                }
            }
        }

        if (payload.hide === true) {
            this.active = false;
            this.speaking = false;
            this.level = 0;
        }

        this.renderState();
    },

    applyInactivePayload: function (payload) {
        if (payload && typeof payload === "object" && payload.level !== undefined) {
            this.level = this.normalizeLevel(payload.level);
        } else {
            this.level = 0;
        }

        if (payload && typeof payload === "object" && typeof payload.speaking === "boolean") {
            this.speaking = payload.speaking;
        } else {
            this.speaking = false;
        }

        this.active = false;
        this.renderState();
    },

    applySpeakingPayload: function (payload) {
        if (typeof payload === "boolean") {
            this.setActive(true);
            this.setSpeaking(payload);
            if (!payload) {
                this.level = 0;
            }
            return;
        }

        this.setActive(true);

        if (payload && typeof payload === "object") {
            if (typeof payload.speaking === "boolean") {
                this.speaking = payload.speaking;
            } else {
                this.speaking = true;
            }

            if (payload.level !== undefined) {
                this.level = this.normalizeLevel(payload.level);
            } else if (this.speaking && this.level < 0.08) {
                this.level = 0.45;
            }

            if (payload.active === false || payload.hide === true) {
                this.active = false;
                this.speaking = false;
                this.level = 0;
            }
        } else {
            this.speaking = true;
            if (this.level < 0.08) {
                this.level = 0.45;
            }
        }

        this.renderState();
    },

    handleBridgeEvent: function (event) {
        if (!event || typeof event !== "object") {
            return;
        }

        const type = String(event.type || "").toLowerCase();
        const level = event.level !== undefined ? this.normalizeLevel(event.level) : undefined;

        if (type === "wakeword" || type === "wake_word" || type === "activated") {
            this.markRtcActive();
            this.active = true;
            this.speaking = false;
            if (level !== undefined) {
                this.level = level;
            }
            this.renderState();
            return;
        }

        if (type === "listening") {
            this.markRtcActive();
            this.active = true;
            this.speaking = false;
            this.level = level !== undefined ? level : 0.08;
            this.renderState();
            return;
        }

        if (type === "speaking") {
            this.markRtcActive();
            this.active = true;
            this.speaking = true;
            this.level = level !== undefined ? level : Math.max(this.level, 0.45);
            this.renderState();
            return;
        }

        if (type === "level") {
            this.markRtcActive();
            this.level = level !== undefined ? level : 0;
            this.active = this.level > 0.02 || this.active;
            this.speaking = this.level > 0.02;
            this.renderState();
            return;
        }

        if (type === "idle") {
            this.markRtcActive();
            this.active = true;
            this.speaking = false;
            this.level = 0;
            this.renderState();
            return;
        }

        if (type === "session_end" || type === "inactive" || type === "hidden") {
            this.active = false;
            this.speaking = false;
            this.level = 0;
            this.renderState();
            return;
        }

        if (type === "state") {
            this.applyStatePayload(event, { keepExisting: false });
        }
    },

    startAnimationLoop: function () {
        if (this.frameTimer) {
            clearInterval(this.frameTimer);
        }

        this.frameTimer = setInterval(() => {
            this.tickAnimation();
        }, this.config.updateInterval);
    },

    tickAnimation: function () {
        const now = Date.now();
        const elapsed = now - this.startedAt;

        if (!this.speaking) {
            this.level *= 0.84;
            if (this.level < 0.01) {
                this.level = 0;
            }
        }

        const isIdle = this.active && !this.speaking && this.lastRtcEventAt > 0 &&
            now - this.lastRtcEventAt > this.config.idleTimeout;

        if (isIdle) {
            this.active = false;
            this.level = 0;
        }

        const targetVisualLevel = this.active ? Math.max(this.level, this.speaking ? 0.18 : 0.02) : 0;
        this.visualLevel += (targetVisualLevel - this.visualLevel) * 0.24;
        this.phase = elapsed / 280;

        if (this.domReady) {
            this.renderBubbleFrame();
        }
    },

    renderState: function () {
        if (!this.domReady) {
            return;
        }

        this.wrapperEl.classList.toggle("is-active", this.active);
        this.wrapperEl.classList.toggle("is-speaking", this.speaking);
        this.renderBubbleFrame();
    },

    renderBubbleFrame: function () {
        if (!this.bubbleEl) {
            return;
        }

        const level = Math.max(0, Math.min(1, this.visualLevel));
        const speakingBoost = this.speaking ? 1 : 0.35;
        const waveA = Math.sin(this.phase) * 0.09 * speakingBoost;
        const waveB = Math.cos(this.phase * 1.27) * 0.08 * speakingBoost;
        const waveC = Math.sin(this.phase * 1.71) * 0.05 * speakingBoost;

        const scaleBase = this.config.minScale + ((this.config.maxScale - this.config.minScale) * level);
        const scaleX = scaleBase + waveA;
        const scaleY = scaleBase + waveB;
        const rotate = (waveA + waveB + waveC) * 18;

        const radiusA = 42 + ((level * 18) + (waveA * 55));
        const radiusB = 58 + ((level * 14) - (waveB * 45));
        const radiusC = 46 + ((level * 16) + (waveC * 50));
        const radiusD = 54 + ((level * 12) - (waveA * 40));
        const glow = 8 + (this.config.glowStrength * level);

        this.bubbleEl.style.setProperty("--bubble-scale-x", scaleX.toFixed(3));
        this.bubbleEl.style.setProperty("--bubble-scale-y", scaleY.toFixed(3));
        this.bubbleEl.style.setProperty("--bubble-rotate", rotate.toFixed(2) + "deg");
        this.bubbleEl.style.setProperty("--radius-a", radiusA.toFixed(1) + "%");
        this.bubbleEl.style.setProperty("--radius-b", radiusB.toFixed(1) + "%");
        this.bubbleEl.style.setProperty("--radius-c", radiusC.toFixed(1) + "%");
        this.bubbleEl.style.setProperty("--radius-d", radiusD.toFixed(1) + "%");
        this.bubbleEl.style.setProperty("--bubble-glow", glow.toFixed(1) + "px");
    },

    setActive: function (active) {
        this.active = active;
        if (!active) {
            this.speaking = false;
            this.level = 0;
        }
        this.renderState();
    },

    setSpeaking: function (speaking) {
        this.speaking = speaking;
        if (speaking) {
            this.active = true;
            this.markRtcActive();
            if (this.level < 0.08) {
                this.level = 0.35;
            }
        }
        this.renderState();
    },

    markRtcActive: function () {
        this.lastRtcEventAt = Date.now();
        if (!this.active) {
            this.active = true;
        }
    },

    registerBridge: function () {
        if (!this.config.bridge || this.config.bridge.enabled === false) {
            return;
        }

        this.sendSocketNotification("MMM_LOCAL_AI_RTC_REGISTER", {
            identifier: this.identifier,
            config: {
                idleTimeout: this.config.idleTimeout,
                bridge: this.config.bridge
            }
        });
    },

    normalizeLevel: function (level) {
        const numericLevel = Number(level);
        if (!Number.isFinite(numericLevel)) {
            return 0;
        }
        return Math.max(0, Math.min(1, numericLevel));
    }
});
