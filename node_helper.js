'use strict';

const http = require('http');
const NodeHelper = require('node_helper');

module.exports = NodeHelper.create({
    start: function () {
        this.server = null;
        this.serverConfig = null;
        this.instances = {};
    },

    socketNotificationReceived: function (notification, payload) {
        if (notification !== 'MMM_LOCAL_AI_RTC_REGISTER' || !payload || !payload.identifier) {
            return;
        }

        this.instances[payload.identifier] = payload.config || {};
        this.ensureServer(payload.config && payload.config.bridge ? payload.config.bridge : {});
    },

    ensureServer: function (bridgeConfig) {
        const normalizedConfig = this.normalizeBridgeConfig(bridgeConfig);
        if (normalizedConfig.enabled === false) {
            return;
        }

        if (this.server &&
            this.serverConfig &&
            this.serverConfig.host === normalizedConfig.host &&
            this.serverConfig.port === normalizedConfig.port &&
            this.serverConfig.path === normalizedConfig.path &&
            this.serverConfig.token === normalizedConfig.token) {
            return;
        }

        if (this.server) {
            this.server.close();
            this.server = null;
        }

        this.serverConfig = normalizedConfig;
        this.server = http.createServer((req, res) => {
            this.handleRequest(req, res);
        });

        this.server.listen(normalizedConfig.port, normalizedConfig.host, () => {
            console.log(
                this.name + ': listening for RTC bridge events on http://' +
                normalizedConfig.host + ':' + normalizedConfig.port + normalizedConfig.path
            );
        });
    },

    normalizeBridgeConfig: function (bridgeConfig) {
        const config = bridgeConfig || {};
        return {
            enabled: config.enabled !== false,
            host: config.host || '127.0.0.1',
            port: Number.isInteger(config.port) ? config.port : 3210,
            path: config.path || '/api/events',
            token: config.token || ''
        };
    },

    handleRequest: function (req, res) {
        if (!this.serverConfig) {
            this.respondJson(res, 503, { ok: false, error: 'Bridge not configured.' });
            return;
        }

        const url = new URL(req.url, 'http://127.0.0.1');
        if (req.method === 'GET' && url.pathname === '/health') {
            this.respondJson(res, 200, { ok: true });
            return;
        }

        if (req.method !== 'POST' || url.pathname !== this.serverConfig.path) {
            this.respondJson(res, 404, { ok: false, error: 'Not found.' });
            return;
        }

        if (!this.isAuthorized(req)) {
            this.respondJson(res, 401, { ok: false, error: 'Unauthorized.' });
            return;
        }

        let body = '';
        req.on('data', (chunk) => {
            body += chunk;
            if (body.length > 1024 * 1024) {
                req.destroy();
            }
        });

        req.on('end', () => {
            this.handleEventBody(body, res);
        });

        req.on('error', (error) => {
            this.respondJson(res, 400, { ok: false, error: error.message });
        });
    },

    isAuthorized: function (req) {
        if (!this.serverConfig || !this.serverConfig.token) {
            return true;
        }

        const authHeader = req.headers.authorization || '';
        return authHeader === 'Bearer ' + this.serverConfig.token;
    },

    handleEventBody: function (body, res) {
        let payload;

        try {
            payload = body ? JSON.parse(body) : {};
        } catch (error) {
            this.respondJson(res, 400, { ok: false, error: 'Invalid JSON.' });
            return;
        }

        if (!payload || typeof payload !== 'object') {
            this.respondJson(res, 400, { ok: false, error: 'Payload must be an object.' });
            return;
        }

        const event = payload.event || payload;
        const targetIdentifier = payload.identifier;
        const targetIdentifiers = targetIdentifier ? [targetIdentifier] : Object.keys(this.instances);

        if (targetIdentifiers.length === 0) {
            this.respondJson(res, 404, { ok: false, error: 'No registered module instances.' });
            return;
        }

        targetIdentifiers.forEach((identifier) => {
            if (!this.instances[identifier]) {
                return;
            }

            this.sendSocketNotification('MMM_LOCAL_AI_RTC_EVENT', {
                identifier: identifier,
                event: event
            });
        });

        this.respondJson(res, 200, {
            ok: true,
            delivered: targetIdentifiers.length,
            type: event.type || 'state'
        });
    },

    respondJson: function (res, statusCode, data) {
        res.writeHead(statusCode, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify(data));
    },

    stop: function () {
        if (this.server) {
            this.server.close();
            this.server = null;
        }
    }
});
