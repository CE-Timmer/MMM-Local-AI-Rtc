#!/usr/bin/with-contenv bashio

set -euo pipefail

export MM_LOCAL_AI_RTC_URL="$(bashio::config 'mirror_bridge_url')"
export MM_LOCAL_AI_RTC_TOKEN="$(bashio::config 'mirror_bridge_token')"
export MM_LOCAL_AI_RTC_IDENTIFIER="$(bashio::config 'mirror_identifier')"
export MM_LOCAL_AI_RTC_IDLE_TIMEOUT="$(bashio::config 'idle_timeout')"

export AI_RTC_BASE_URL="$(bashio::config 'rtc_base_url')"
export AI_RTC_TOKEN="$(bashio::config 'rtc_token')"
export AI_RTC_CONVERSATION_ID="$(bashio::config 'conversation_id')"
export AI_RTC_STT_LANGUAGE="$(bashio::config 'stt_language')"
export AI_RTC_VOICEPRINT_GATE="$(bashio::config 'voiceprint_gate')"
export AI_RTC_VOICEPRINT_CHECK_STATUS="$(bashio::config 'voiceprint_check_status')"
export AI_RTC_VOICEPRINT_DELETE_BEFORE_ENROLL="$(bashio::config 'voiceprint_delete_before_enroll')"
export AI_RTC_VOICEPRINT_ENROLL_AUDIO_PATH="$(bashio::config 'voiceprint_enroll_audio_path')"
export AI_RTC_VOICEPRINT_ENROLL_AUDIO_URL="$(bashio::config 'voiceprint_enroll_audio_url')"
export AI_RTC_OUTPUT_DEVICE="$(bashio::config 'output_device')"
export AI_RTC_PLAY_REMOTE_AUDIO="$(bashio::config 'play_remote_audio')"

export OWW_MODEL="$(bashio::config 'wakeword_model')"
export OWW_MODEL_FILE="$(bashio::config 'wakeword_model_file')"
export OWW_MODEL_URL="$(bashio::config 'wakeword_model_url')"
export OWW_THRESHOLD="$(bashio::config 'wakeword_threshold')"
export OWW_VAD_THRESHOLD="$(bashio::config 'wakeword_vad_threshold')"
export OWW_MIC_DEVICE="$(bashio::config 'mic_device')"

bashio::log.info "Starting Local AI RTC Bridge add-on"
python /app/local_ai_rtc_bridge.py
