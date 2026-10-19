//! Preserve provider terminal evidence from HTTP reconstruction through detection.

mod common;

use agentsight::aggregator::Aggregator;
use agentsight::analyzer::{AnalysisResult, Analyzer, HttpRecord};
use agentsight::config::RuntimeLimits;
use agentsight::event::Event;
use agentsight::genai::GenAIBuilder;
use agentsight::genai::semantic::{GenAISemanticEvent, LLMCall};
use agentsight::interruption::{InterruptionDetector, InterruptionType};
use agentsight::parser::Parser;
use agentsight::response_map::ResponseSessionMapper;
use serde_json::{Value, json};
use std::collections::HashMap;

fn build(results: &[AnalysisResult]) -> LLMCall {
    GenAIBuilder::new()
        .build_with_pending(results, &ResponseSessionMapper::disabled(), &HashMap::new())
        .0
        .events
        .into_iter()
        .find_map(|event| match event {
            GenAISemanticEvent::LLMCall(call) => Some(call),
            _ => None,
        })
        .expect("one reconstructed LLM call")
}

fn response(reason: &str, content: bool) -> Value {
    let mut candidate = json!({"finishReason": reason, "index": 0});
    if content {
        candidate["content"] = json!({"role": "model", "parts": [{"text": "partial"}]});
    }
    json!({"candidates": [candidate]})
}

fn raw_call(reason: &str, content: bool, streaming: bool) -> LLMCall {
    let payload = response(reason, content);
    build(&[AnalysisResult::Http(HttpRecord {
        timestamp_ns: 1_000_000_000,
        pid: std::process::id(),
        comm: "fixture".into(),
        method: "POST".into(),
        path: format!(
            "/v1beta/models/gemini-fixture:{}",
            if streaming {
                "streamGenerateContent"
            } else {
                "generateContent"
            }
        ),
        status_code: 200,
        request_headers: "{}".into(),
        request_body: Some(
            json!({"contents": [{"role":"user","parts":[{"text":"hello"}]}]}).to_string(),
        ),
        response_headers: "{}".into(),
        response_body: Some(if streaming {
            json!([payload]).to_string()
        } else {
            payload.to_string()
        }),
        duration_ns: 2_000_000_000,
        first_output_timestamp_ns: None,
        is_sse: streaming,
        sse_event_count: usize::from(streaming),
    })])
}

fn cached_stream(reason: &str, content: bool, retain_raw: bool) -> LLMCall {
    let mut aggregator = Aggregator::with_limits(
        16,
        &RuntimeLimits {
            retain_raw_sse: retain_raw,
            ..Default::default()
        },
    );
    let request = json!({"contents": [{"role":"user","parts":[{"text":"hello"}]}]}).to_string();
    let request = format!(
        "POST /v1beta/models/gemini-fixture:streamGenerateContent?alt=sse HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{request}",
        request.len()
    );
    let payload = format!("data: {}\n\n", response(reason, content));
    let mut results = Vec::new();
    for (rw, timestamp, bytes) in [
        (1, 1_000_000_000, request.into_bytes()),
        (0, 2_000_000_000, common::make_openai_sse_response_headers()),
        (0, 3_000_000_000, payload.into_bytes()),
    ] {
        let mut event = common::make_ssl_event(std::process::id(), 42, rw, bytes, "fixture");
        event.timestamp_ns = timestamp;
        results.extend(aggregator.process_result(Parser::new().parse_event(Event::Ssl(event))));
    }
    assert_eq!(
        results.len(),
        1,
        "terminal finishReason completes the stream"
    );
    assert!(!aggregator.has_pending());
    build(&Analyzer::new().analyze_aggregated(&results[0]))
}

fn assert_terminal(call: &LLMCall, reason: &str, expected: InterruptionType) {
    assert_eq!(
        call.response.messages.len(),
        1,
        "{reason}: terminal-only evidence must survive"
    );
    assert_eq!(
        call.response.messages[0].finish_reason.as_deref(),
        Some(reason)
    );
    let events = InterruptionDetector::default().detect(call);
    assert_eq!(events.len(), 1, "{reason}: {events:?}");
    assert_eq!(events[0].interruption_type, expected, "{reason}");
    let detail: Value = serde_json::from_str(events[0].detail.as_ref().unwrap()).unwrap();
    assert_eq!(detail["finish_reason"], reason);
}

#[test]
fn gemini_blocked_completions_are_safety_filters() {
    for reason in [
        "SAFETY",
        "RECITATION",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_RECITATION",
    ] {
        for streaming in [false, true] {
            for content in [false, true] {
                assert_terminal(
                    &raw_call(reason, content, streaming),
                    reason,
                    InterruptionType::SafetyFilter,
                );
            }
        }
    }
}

#[test]
fn gemini_invalid_completions_are_protocol_interruptions() {
    for reason in [
        "MALFORMED_FUNCTION_CALL",
        "UNEXPECTED_TOOL_CALL",
        "MALFORMED_RESPONSE",
    ] {
        for streaming in [false, true] {
            for content in [false, true] {
                assert_terminal(
                    &raw_call(reason, content, streaming),
                    reason,
                    InterruptionType::StateMachineError,
                );
            }
        }
    }
}

#[test]
fn gemini_cached_pipeline_keeps_terminal_only_evidence() {
    for (reason, expected) in [
        ("SAFETY", InterruptionType::SafetyFilter),
        (
            "MALFORMED_FUNCTION_CALL",
            InterruptionType::StateMachineError,
        ),
    ] {
        for retain_raw in [false, true] {
            for content in [false, true] {
                assert_terminal(
                    &cached_stream(reason, content, retain_raw),
                    reason,
                    expected.clone(),
                );
            }
        }
    }
}

#[test]
fn gemini_terminal_classification_preserves_http_error_priority() {
    for (status, expected) in [
        (401, InterruptionType::AuthError),
        (429, InterruptionType::RateLimit),
        (504, InterruptionType::NetworkTimeout),
        (503, InterruptionType::ServiceUnavailable),
    ] {
        for reason in ["SAFETY", "MALFORMED_FUNCTION_CALL"] {
            let mut call = raw_call(reason, true, true);
            call.metadata
                .insert("status_code".into(), status.to_string());
            let events = InterruptionDetector::default().detect(&call);
            assert_eq!(events.len(), 1);
            assert_eq!(events[0].interruption_type, expected);
        }
    }
}

#[test]
fn gemini_terminal_evidence_does_not_rewrite_finish_reasons() {
    for reason in [
        "STOP",
        "MAX_TOKENS",
        "OTHER",
        "LANGUAGE",
        "FINISH_REASON_UNSPECIFIED",
    ] {
        for content in [false, true] {
            let call = raw_call(reason, content, true);
            assert_eq!(call.response.messages.len(), 1);
            assert_eq!(
                call.response.messages[0].finish_reason.as_deref(),
                Some(reason)
            );
            let events = InterruptionDetector::default().detect(&call);
            assert!(events.iter().all(|event| !matches!(
                event.interruption_type,
                InterruptionType::SafetyFilter | InterruptionType::StateMachineError
            )));
        }
    }
}

#[test]
fn missing_gemini_terminal_reason_still_reports_truncation() {
    for content in [false, true] {
        let call = raw_call("", content, true);
        let events = InterruptionDetector::default().detect(&call);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].interruption_type, InterruptionType::SseTruncated);
    }
}

#[test]
fn terminal_only_openai_safety_evidence_also_survives() {
    let results = [AnalysisResult::Http(HttpRecord {
        timestamp_ns: 1_000_000_000,
        pid: std::process::id(),
        comm: "fixture".into(),
        method: "POST".into(),
        path: "/v1/chat/completions".into(),
        status_code: 200,
        request_headers: "{}".into(),
        request_body: None,
        response_headers: "{}".into(),
        response_body: Some(
            json!([{"choices": [{"delta": {}, "finish_reason": "content_filter"}]}]).to_string(),
        ),
        duration_ns: 2_000_000_000,
        first_output_timestamp_ns: None,
        is_sse: true,
        sse_event_count: 1,
    })];
    assert_terminal(
        &build(&results),
        "content_filter",
        InterruptionType::SafetyFilter,
    );
}
