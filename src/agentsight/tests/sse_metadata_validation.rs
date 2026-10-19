//! Parse captured SSE fields without exporting invalid metadata.
#![cfg(target_os = "linux")]

mod common;

use agentsight::parser::sse::{SSEParser, SseParser};
use std::rc::Rc;

fn assert_metadata(fields: &str, id: Option<&str>, retry: Option<u64>) {
    for ending in ["\n", "\r", "\r\n"] {
        let input = format!("{fields}event: custom\ndata: 中🙂\n\n").replace('\n', ending);
        let source = Rc::new(common::make_ssl_event(
            123,
            0x123,
            0,
            input.as_bytes().to_vec(),
            "fixture",
        ));
        let parsed = SseParser::new().parse(Rc::clone(&source));
        assert_eq!(parsed.len(), 1, "{fields:?}");
        assert_eq!(parsed[0].id.as_deref(), id, "{fields:?}");
        assert_eq!(parsed[0].retry, retry, "{fields:?}");
        assert_eq!(parsed[0].data(), "中🙂".as_bytes());
        assert_eq!(parsed[0].event.as_deref(), Some("custom"));
        assert!(std::ptr::eq(parsed[0].source_event(), source.as_ref()));

        let legacy = SSEParser::parse_stream(&input);
        assert_eq!(legacy.events.len(), 1);
        assert_eq!(legacy.events[0].id.as_deref(), id, "legacy {fields:?}");
        assert_eq!(legacy.events[0].retry, retry, "legacy {fields:?}");
        let trace = legacy.events[0].to_chrome_trace_event(123, 123, 0);
        let args = trace.args.unwrap();
        assert_eq!(args.get("id").and_then(|v| v.as_str()), id);
        assert_eq!(args.get("retry").and_then(|v| v.as_u64()), retry);
        assert_eq!(args["data"], "中🙂");
        let encoded = legacy.events[0].to_sse_string();
        let roundtrip = SSEParser::parse_stream(&encoded);
        assert_eq!(roundtrip.events[0].id.as_deref(), id);
        assert_eq!(roundtrip.events[0].retry, retry);
    }
}

#[test]
fn invalid_retry_does_not_replace_a_valid_hint() {
    for value in [
        "",
        "+1",
        "-1",
        "1.0",
        "1 2",
        " 50",
        "50 ",
        "\t50",
        "١",
        "18446744073709551616",
    ] {
        assert_metadata(&format!("retry: 500\nretry: {value}\n"), None, Some(500));
    }
    assert_metadata("retry: 500\nretry\n", None, Some(500));
}

#[test]
fn invalid_retry_alone_does_not_invent_a_hint() {
    assert_metadata("retry: +1\n", None, None);
    assert_metadata("retry\n", None, None);
    assert_metadata("retry:\n", None, None);
}

#[test]
fn null_id_is_ignored_without_replacing_valid_id() {
    assert_metadata("id: stable\nid: invalid\0id\n", Some("stable"), None);
    assert_metadata("id: \0\n", None, None);
}

#[test]
fn empty_id_and_valid_decimal_retry_remain_supported() {
    assert_metadata("id: before\nid\nretry: 0007\n", Some(""), Some(7));
    assert_metadata("id: before\nid:\nretry: 0\n", Some(""), Some(0));
    assert_metadata(
        "id: 中文🙂\nretry: 18446744073709551615\n",
        Some("中文🙂"),
        Some(u64::MAX),
    );
    assert_metadata("retry: 5\nretry: 8\n", None, Some(8));
}

#[test]
fn invalid_metadata_only_blocks_do_not_invent_events() {
    let input = "retry\n\nid: bad\0id\n\ndata: kept\n\n";
    let source = Rc::new(common::make_ssl_event(
        123,
        0x123,
        0,
        input.as_bytes().to_vec(),
        "fixture",
    ));
    let events = SseParser::new().parse(source);
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].data(), b"kept");
    let legacy = SSEParser::parse_stream(input);
    assert_eq!(legacy.events.len(), 1);
    assert_eq!(legacy.events[0].data, "kept");
}
